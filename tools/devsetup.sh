#!/bin/bash
set -euo pipefail

# Ensure we're in the project root
PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

DATA_DIR="data/ds007070-fmriprep"
CATALOG="data/ds007070.duckdb"

echo "Downloading sample data from OpenNeuro (ds007070)..."
mkdir -p "$DATA_DIR"

for SUB in "sub-0001" "sub-0002"; do
	# anat files
	aws s3 sync --no-sign-request "s3://openneuro.org/ds007070/$SUB/ses-01/anat/" "$DATA_DIR/$SUB/ses-01/anat/" --exclude "*" --include "*desc-brain_mask.nii.gz" --include "*desc-preproc_T1w.nii.gz" --include "*.json"

	# func files needed for both coregistration checks. Nothing is pinned after
	# the `to-` value: the boldref->T1w affine carries a `desc-coreg` before the
	# suffix, which the fieldmap ones do not.
	aws s3 sync --no-sign-request "s3://openneuro.org/ds007070/$SUB/ses-01/func/" "$DATA_DIR/$SUB/ses-01/func/" --exclude "*" --include "*desc-brain_mask.nii.gz" --include "*desc-coreg_boldref.nii.gz" --include "*from-boldref_to-*_xfm.txt" --include "*.json"

	# fmap files
	aws s3 sync --no-sign-request "s3://openneuro.org/ds007070/$SUB/ses-01/fmap/" "$DATA_DIR/$SUB/ses-01/fmap/" --exclude "*" --include "*desc-epi_fieldmap.nii.gz" --include "*desc-preproc_fieldmap.nii.gz" --include "*.json"

	# freesurfer files
	aws s3 sync --no-sign-request "s3://openneuro.org/ds007070/sourcedata/freesurfer/$SUB/mri/" "$DATA_DIR/sourcedata/freesurfer/$SUB/mri/" --exclude "*" --include "brain.mgz" --include "ribbon.mgz"
done

# Add a dataset_description.json so b2t2 recognizes it as a valid derivative dataset
echo '{
    "Name": "ds007070-fmriprep-subset",
    "BIDSVersion": "1.4.0",
    "DatasetType": "derivative",
    "GeneratedBy": [{"Name": "fmriprep"}]
}' >"$DATA_DIR/dataset_description.json"

echo "Indexing dataset with bidslake..."
# Start from a fresh catalog: bidslake re-index upserts these days, but a
# catalog written by an older bidslake format is unreadable by the current
# reader, so a clean rebuild keeps devsetup idempotent across bidslake bumps.
# (`bidslake compact` reclaims space if you keep a catalog instead.)
rm -f "$CATALOG" "${CATALOG}.wal"
# A shared catalog's physical shape is frozen by the run that creates it, and an
# adapter widens it — so every index run into the catalog passes the union of
# adapters any of its datasets needs (here: freesurfer), or bidslake refuses
# the mismatched run.
pixi run -e manage bidslake index -i "$DATA_DIR" --adapter freesurfer -o "$CATALOG"
# FreeSurfer recon-all is standardized but not BIDS; index it as its own dataset
# with the adapter (the sourcedata/ nesting defeats the term-map anchor otherwise).
pixi run -e manage bidslake index -i "$DATA_DIR/sourcedata/freesurfer" \
	--adapter freesurfer --dataset-id freesurfer -o "$CATALOG"

echo "Applying database migrations..."
# Set up env vars for local sqlite (WAL sidecar files live in db/ too)
mkdir -p "${PROJECT_ROOT}/db"
export DB="${PROJECT_ROOT}/db/dirt.db"
export DJANGO_DEBUG=True
export DJANGO_SECRET_KEY='dev-secret-key-do-not-u1se-in-prod'

pixi run -e manage manage migrate
pixi run -e manage manage createcachetable --database cache

echo "Creating superuser (admin / admin)..."
# Create superuser if it doesn't exist
pixi run -e manage manage shell -c "
from django.contrib.auth import get_user_model;
User = get_user_model();
User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin', 'admin@example.com', 'admin')
"

echo "Rendering QC images from the catalog (this may take a minute)..."
# `render` auto-discovers which steps have files present in the catalog. The
# sample covers masks, spatial normalization, surface localization, and fmap
# coregistration (it has no DWI, so DTI-fit is skipped).
pixi run -e manage manage render "$CATALOG"

# Write the env file the docker run below uses. DB points at the container's
# mount (/app/db), so the container serves the database populated above rather
# than a fresh, empty one. (.env.docker is gitignored, so it is generated here.)
cat >"${PROJECT_ROOT}/.env.docker" <<'ENVEOF'
DJANGO_SECRET_KEY='django-insecure-dev-key-do-not-use-in-prod'
DB=/app/db/dirt.db
DJANGO_DEBUG=True
ENVEOF

echo ""
echo "Setup complete! You can now run the development server using Docker:"
echo "  docker buildx build -t psadil/dirt --platform=linux/amd64 --provenance=true ."
echo "  docker run --rm -it -v \$PWD/db:/app/db --env-file=.env.docker -p 8000:8000 psadil/dirt"
echo ""
echo "Log in at http://localhost:8000/admin/ with username: admin, password: admin"
