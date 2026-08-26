"""Build the canonical spatial-normalization landmark image (one-time, dev-time).

Downloads the Benhajali et al. 2020 hand-drawn sulcal landmark bands from
SIMEXP/brain_match (MIT license) at a pinned commit, mirrors the left-side
drawings across the symmetric template's midline to obtain the right side
(brain_match did the same — their left/right layout masks have identical voxel
counts), registers the drawings' native template (ICBM 2009a *symmetric*) to
TemplateFlow ``MNI152NLin2009cAsym`` with dipy affine+SyN on gray-matter
probability maps, warps each band, and composes a labeled dseg.

Only structures with no atlas source are taken from the drawings (central and
cingulate sulci, calcarine, parieto-occipital fissure, tentorium cerebelli);
ventricles and hippocampi come procedurally from each space's Harvard-Oxford
atlas at build time (see ``management/ingest/rois.py``), and the brain-outline
band is always procedural.

Outputs (commit all of them):
- src/django_dirt_ratings/data/tpl-MNI152NLin2009cAsym_desc-landmarks_dseg.nii.gz
- src/django_dirt_ratings/data/tpl-MNI152NLin2009cAsym_desc-landmarks_dseg.json
- src/django_dirt_ratings/data/PROVENANCE.md
- QC figures under docs/assets/concepts/landmarks/ (shown on the
  "Landmark warp QC" docs page so users can verify the warp)

Run:  pixi run -e dev python tools/make_landmarks.py
      pixi run -e dev python tools/make_landmarks.py --figures-only
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import urllib.request
from pathlib import Path

import nibabel as nb
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from django_dirt_ratings.management.ingest import rois

BRAIN_MATCH_COMMIT = "58476047cf43b30425eb35cb414890ce99c318c0"
BRAIN_MATCH_LFS = (
    "https://media.githubusercontent.com/media/SIMEXP/brain_match/"
    f"{BRAIN_MATCH_COMMIT}/data/Misc/landmarks"
)
# brain_match raw drawing -> our structure stem (left side; rights are mirrored)
SOURCES = {
    "left_central_sulcus.nii.gz": "central_sulcus",
    "left_cingulate_sulcus.nii.gz": "cingulate_sulcus",
    "left_calcarine_sulcus.nii.gz": "calcarine_sulcus",
    "left_parieto-occipital_fissure.nii.gz": "parieto_occipital_fissure",
    "left_tentorium_cerebelli.nii.gz": "tentorium_cerebelli",
}
GM_09A = "mni_icbm152_gm_tal_nlin_sym_09a.nii.gz"
MASK_09A = "mni_icbm152_t1_tal_nlin_sym_09a_mask.nii.gz"

DATA_DIR = REPO / "src" / "django_dirt_ratings" / "data"
DSEG_NAME = "tpl-MNI152NLin2009cAsym_desc-landmarks_dseg.nii.gz"
QC_DIR = REPO / "docs" / "assets" / "concepts" / "landmarks"


def fetch(work: Path, name: str) -> Path:
    dst = work / name
    if not dst.exists():
        print(f"  fetching {name}")
        urllib.request.urlretrieve(f"{BRAIN_MATCH_LFS}/{name}", dst)
    return dst


def mirror(arr: np.ndarray, affine: np.ndarray) -> np.ndarray:
    """Flip across the x=0 midplane; exact only on a symmetric-origin grid."""
    center = -affine[0, 3] / affine[0, 0]
    if abs(center - (arr.shape[0] - 1) / 2) > 0.01:
        raise ValueError(
            f"grid is not symmetric about x=0 (center voxel {center}); "
            "cannot mirror by array flip"
        )
    return arr[::-1]


def register(work: Path):
    """dipy affine+SyN of 09a-sym GM onto TemplateFlow 2009cAsym GM."""
    import templateflow.api as tf
    from dipy.align.imaffine import (
        AffineRegistration,
        MutualInformationMetric,
        transform_centers_of_mass,
    )
    from dipy.align.imwarp import SymmetricDiffeomorphicRegistration
    from dipy.align.metrics import CCMetric
    from dipy.align.transforms import (  # ty: ignore[unresolved-import]
        AffineTransform3D,
        RigidTransform3D,
    )

    fix_gm_path = Path(
        tf.get(rois.CANONICAL_SPACE, label="GM", suffix="probseg", resolution=1)
    )
    fix_mask_path = Path(
        tf.get(rois.CANONICAL_SPACE, desc="brain", suffix="mask", resolution=1)
    )
    mov_gm_path = fetch(work, GM_09A)

    fix_img = rois._load(fix_gm_path)
    mov_img = rois._load(mov_gm_path)
    fix = fix_img.get_fdata()
    mov = mov_img.get_fdata()
    sg, mg = fix_img.affine, mov_img.affine

    com = transform_centers_of_mass(fix, sg, mov, mg)
    affreg = AffineRegistration(
        metric=MutualInformationMetric(nbins=32),
        level_iters=[10000, 1000, 100],
        sigmas=[3.0, 1.0, 0.0],
        factors=[4, 2, 1],
        verbosity=0,
    )
    rigid = affreg.optimize(
        fix,
        mov,
        RigidTransform3D(),
        None,
        static_grid2world=sg,
        moving_grid2world=mg,
        starting_affine=com.affine,
    )
    affine = affreg.optimize(
        fix,
        mov,
        AffineTransform3D(),
        None,
        static_grid2world=sg,
        moving_grid2world=mg,
        starting_affine=rigid.affine,
    )
    sdr = SymmetricDiffeomorphicRegistration(CCMetric(3), level_iters=[100, 50, 25])
    mapping = sdr.optimize(
        fix, mov, static_grid2world=sg, moving_grid2world=mg, prealign=affine.affine
    )

    from nilearn import image

    fix_mask = np.asarray(rois._load(fix_mask_path).dataobj) > 0
    warped_gm = mapping.transform(
        mov,
        interpolation="linear",
        image_world2grid=np.linalg.inv(mg),
        out_shape=fix_img.shape,
        out_grid2world=sg,
    )
    identity_gm = np.asarray(
        image.resample_to_img(
            mov_img,
            fix_img,
            interpolation="linear",
            force_resample=True,
            copy_header=True,
        ).dataobj
    )
    ref = fix[fix_mask]
    r_warp = float(np.corrcoef(warped_gm[fix_mask], ref)[0, 1])
    r_identity = float(np.corrcoef(identity_gm[fix_mask], ref)[0, 1])
    print(
        f"  GM correlation within brain: identity {r_identity:.4f} -> warped {r_warp:.4f}"
    )
    if r_warp <= r_identity:
        raise SystemExit("registration did not improve on identity; aborting")

    import dipy

    provenance = {
        "engine": f"dipy {dipy.__version__} affine(MI)+SyN(CC) on GM probability maps",
        "moving": {GM_09A: rois._sha256(mov_gm_path)},
        "static": {
            fix_gm_path.name: rois._sha256(fix_gm_path),
            fix_mask_path.name: rois._sha256(fix_mask_path),
        },
        "r_identity": round(r_identity, 4),
        "r_warp": round(r_warp, 4),
    }
    return mapping, mov_img, fix_img, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path.home() / ".cache" / "dirt" / "make-landmarks",
        help="download + QC scratch directory (kept for re-runs)",
    )
    parser.add_argument(
        "--figures-only",
        action="store_true",
        help="re-render the QC figures from the committed dseg "
        "(no download or registration)",
    )
    args = parser.parse_args()
    if args.figures_only:
        qc_figures(DATA_DIR / DSEG_NAME)
        print(f"QC figures in {QC_DIR}")
        return
    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)

    print("downloading brain_match sources (pinned commit)")
    source_paths = {name: fetch(work, name) for name in SOURCES}
    fetch(work, MASK_09A)  # recorded for provenance/QC even though unused directly

    print("registering ICBM 2009a-sym -> MNI152NLin2009cAsym (dipy)")
    mapping, _mov_img, fix_img, registration = register(work)

    print("warping and mirroring landmarks")
    data = np.zeros(fix_img.shape, dtype=np.uint8)
    labels: dict[str, int] = {}
    structures: dict[str, dict] = {}
    for src_name, stem in SOURCES.items():
        src_img = rois._load(source_paths[src_name])
        left = np.asarray(src_img.dataobj) > 0
        for side, native in (("left", left), ("right", mirror(left, src_img.affine))):
            name = f"{side}_{stem}"
            warped = mapping.transform(
                native.astype(np.int16),
                interpolation="nearest",
                image_world2grid=np.linalg.inv(src_img.affine),
                out_shape=fix_img.shape,
                out_grid2world=fix_img.affine,
            ).astype(bool)
            cleaned, cleanup = rois._cleanup_warped(warped, name)
            label = rois.LABELS[name]
            data[cleaned] = label
            labels[name] = label
            structures[name] = {
                "source": f"SIMEXP/brain_match@{BRAIN_MATCH_COMMIT} {src_name}"
                + ("" if side == "left" else " (mirrored across x=0)"),
                "input_sha256": rois._sha256(source_paths[src_name]),
                "cleanup": cleanup,
            }
            print(f"  {name}: {cleanup['voxels_after']} voxels")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dseg_path = DATA_DIR / DSEG_NAME
    out_img = nb.nifti1.Nifti1Image(data, fix_img.affine, dtype=np.uint8)
    # A default header carries qform_code=0/sform_code=ALIGNED and no units;
    # inherit the reference's space code (MNI152 on TemplateFlow templates) so
    # external tools that read NIfTI codes rather than affines see the space.
    out_img.header.set_qform(fix_img.affine, code=int(fix_img.header["sform_code"]))
    out_img.header.set_sform(fix_img.affine, code=int(fix_img.header["sform_code"]))
    out_img.header.set_xyzt_units(xyz="mm")
    rois._atomic_write_nifti(out_img, dseg_path)
    sidecar = {
        # BIDS derivative sidecar fields (SpatialReference, Sources) alongside
        # the bespoke provenance keys.
        "SpatialReference": "https://templateflow.s3.amazonaws.com/"
        f"tpl-{rois.CANONICAL_SPACE}/tpl-{rois.CANONICAL_SPACE}_res-01_T1w.nii.gz",
        "Sources": [
            f"{BRAIN_MATCH_LFS}/{name}" for name in [*SOURCES, GM_09A, MASK_09A]
        ],
        "built": datetime.datetime.now(tz=datetime.UTC).date().isoformat(),
        "brain_match_commit": BRAIN_MATCH_COMMIT,
        "license": "MIT (SIMEXP/brain_match)",
        "reference": "Benhajali et al. 2020, doi:10.3389/fninf.2020.00007",
        "registration": registration,
        "labels": labels,
        "structures": structures,
    }
    meta_path = dseg_path.parent / (DSEG_NAME.removesuffix(".nii.gz") + ".json")
    rois._atomic_write_text(json.dumps(sidecar, indent=2, sort_keys=True), meta_path)

    write_provenance(sidecar)
    qc_figures(dseg_path)
    print(f"\nwrote {dseg_path}\nwrote {meta_path}\nQC figures in {QC_DIR}")


def write_provenance(sidecar: dict) -> None:
    reg = sidecar["registration"]
    lines = [
        "# Provenance: canonical landmark image",
        "",
        f"`{DSEG_NAME}` — hand-drawn landmark bands from Benhajali et al. 2020",
        "(doi:10.3389/fninf.2020.00007), fetched from",
        "[SIMEXP/brain_match](https://github.com/SIMEXP/brain_match) (MIT) at commit",
        f"`{sidecar['brain_match_commit']}`, built {sidecar['built']} by",
        "`tools/make_landmarks.py`. Full per-structure detail (source files, sha256s,",
        "cleanup voxel counts) lives in the sidecar JSON next to the image.",
        "",
        "## Why these sources",
        "",
        "The raw per-structure drawings (`data/Misc/landmarks/*.nii.gz`) are each a",
        "single connected component with zero interior holes. The previously bundled",
        "mask derived instead from brain_match's degraded composite",
        "(`mask_layout/mask_all_layout.nii.gz`: 48 fragments, 436 hole voxels)",
        "resliced across mismatched grids (their 197x233x189 ICBM-09a grid vs the",
        "193x229x193 2009c grid), which produced the fragmented, holey overlay this",
        "replaces. Right-side structures are the left drawings mirrored across x=0,",
        "exact on the symmetric template (brain_match's own right-side layout masks",
        "are identical mirrors).",
        "",
        "## Space",
        "",
        "The drawings live on the ICBM 2009a *symmetric* template. They were moved to",
        f"`MNI152NLin2009cAsym` by {reg['engine']}, gated on improving the",
        "within-brain GM correlation over identity world-coordinate placement:",
        f"identity r = {reg['r_identity']}, warped r = {reg['r_warp']}.",
        "(Identity placement is already close — brain-mask Dice 0.989, mean surface",
        "distance 0.5 mm — and the bands are ~10 mm wide, so the registration is a",
        "refinement, not a rescue.)",
        "",
        "TemplateFlow's curated inter-template `*_xfm.h5` composites were evaluated",
        "for the per-space warps and rejected: applied through nitransforms they",
        "*lowered* masked-T1w correlation below identity (0.66 vs 0.78 for",
        "MNI152NLin6Asym), indicating a displacement-field convention mismatch, so",
        "`management/ingest/rois.py` computes and validates its own dipy",
        "registrations instead.",
        "",
        "## Regenerating",
        "",
        "```bash",
        "pixi run -e dev python tools/make_landmarks.py",
        "```",
    ]
    (DATA_DIR / "PROVENANCE.md").write_text("\n".join(lines) + "\n")


def qc_figures(dseg_path: Path) -> None:
    """Overlay the composed landmarks on the target T1w at the display cuts.

    Written as committed docs assets (AVIF, same idiom as
    ``tools/make_tutorial_images.py``) and shown on the "Landmark warp QC"
    docs page so users can verify the warp.
    """
    import io

    import templateflow.api as tf
    from matplotlib import pyplot as plt
    from nilearn import plotting
    from PIL import Image

    t1w = str(tf.get(rois.CANONICAL_SPACE, desc=None, suffix="T1w", resolution=1))
    display_cuts = {"x": [-50, 5, 30], "y": [-65, 20, 54], "z": [-6, 13, 58]}
    QC_DIR.mkdir(parents=True, exist_ok=True)
    for axis, cuts in display_cuts.items():
        f = plt.figure(figsize=(12, 4.8))
        p = plotting.plot_roi(
            roi_img=str(dseg_path),
            bg_img=t1w,
            display_mode=axis,
            cut_coords=cuts,
            figure=f,
            colorbar=False,
        )
        buffer = io.BytesIO()
        p.savefig(buffer, dpi=150)
        plt.close(f)
        buffer.seek(0)
        Image.open(buffer).convert("RGB").save(
            QC_DIR / f"qc_landmarks_{axis}.avif",
            quality=100,
            subsampling="4:4:4",
            speed=6,
        )


if __name__ == "__main__":
    main()
