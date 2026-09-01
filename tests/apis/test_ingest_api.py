"""Tests for the authenticated ingest API (django-ninja)."""

import base64
import io
import tarfile

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile

from django_dirt_ratings import storage, transfer
from django_dirt_ratings.api import INGEST_GROUP
from django_dirt_ratings.models import (
    Annotation,
    DisplayMode,
    Image,
    Rating,
    Ratings,
    ReviewPlan,
)

#: A minimal ISO-BMFF ftyp box with the avif brand — enough for the sniff.
AVIF = b"\x00\x00\x00\x20ftypavif" + b"\x00" * 20
AVIF_B = b"\x00\x00\x00\x20ftypavis" + b"\x00" * 24

PLAN_TOML = "[steps.masks]\n"


@pytest.fixture
def ingest_enabled(settings):
    settings.INGEST_ENABLED = True


@pytest.fixture
def pusher(db, django_user_model):
    """An account in the ingest group (the kind create_rater --ingest makes)."""
    user = django_user_model.objects.create_user("pusher", password="pw")
    group, _ = Group.objects.get_or_create(name=INGEST_GROUP)
    user.groups.add(group)
    return user


@pytest.fixture
def auth(ingest_enabled, pusher) -> dict:
    token = base64.b64encode(b"pusher:pw").decode()
    return {"headers": {"authorization": f"Basic {token}"}}


def _tar(members: list[tuple[int, int | None, bytes]]) -> bytes:
    buffer = io.BytesIO()
    transfer.write_unit_tar(members, buffer)
    return buffer.getvalue()


def _unit_payload(**overrides) -> dict:
    payload = {
        "step": "masks",
        "file1": "sub-01_mask.nii.gz",
        "file2": None,
        "entities": {"space": "MNI"},
        "metrics": {"mask_volume": 100.0},
        "plan_hash": None,
        "images": [
            {"display": 0, "slice": 0, "digest": transfer.content_digest(AVIF)},
            {"display": 1, "slice": 1, "digest": transfer.content_digest(AVIF_B)},
        ],
    }
    return payload | overrides


def _post_unit(client, auth, payload: dict | None = None, tar: bytes | None = None):
    import orjson

    body = orjson.dumps(payload if payload is not None else _unit_payload())
    if tar is None:
        tar = _tar([(0, 0, AVIF), (1, 1, AVIF_B)])
    return client.post(
        "/api/units",
        data={
            "unit": SimpleUploadedFile("unit.json", body, "application/json"),
            "images": SimpleUploadedFile("images.tar", tar, "application/x-tar"),
        },
        **auth,
    )


@pytest.mark.django_db
class TestAuth:
    def test_no_credentials_is_401(self, client, ingest_enabled):
        response = client.get("/api/units?step=masks")

        assert response.status_code == 401

    def test_wrong_group_is_401(self, client, ingest_enabled, django_user_model):
        django_user_model.objects.create_user("norm", password="pw")
        token = base64.b64encode(b"norm:pw").decode()

        response = client.get(
            "/api/units?step=masks", headers={"authorization": f"Basic {token}"}
        )

        assert response.status_code == 401

    def test_disabled_ingest_is_401_even_with_credentials(self, client, pusher):
        token = base64.b64encode(b"pusher:pw").decode()

        response = client.get(
            "/api/units?step=masks", headers={"authorization": f"Basic {token}"}
        )

        assert response.status_code == 401


@pytest.mark.django_db
class TestPlanEndpoints:
    def test_no_active_plan_reads_as_null(self, client, auth):
        response = client.get("/api/plan", **auth)

        assert response.json() is None

    def test_pushing_a_plan_activates_it(self, client, auth):
        client.post(
            "/api/plan",
            data={"name": "t", "toml": PLAN_TOML},
            content_type="application/json",
            **auth,
        )

        assert ReviewPlan.objects.get().is_active is True

    def test_pushing_twice_is_idempotent(self, client, auth):
        for _ in range(2):
            client.post(
                "/api/plan",
                data={"name": "t", "toml": PLAN_TOML},
                content_type="application/json",
                **auth,
            )

        assert ReviewPlan.objects.count() == 1

    def test_the_active_plan_reads_back(self, client, auth):
        pushed = client.post(
            "/api/plan",
            data={"name": "t", "toml": PLAN_TOML},
            content_type="application/json",
            **auth,
        ).json()

        assert client.get("/api/plan", **auth).json() == pushed

    def test_an_invalid_plan_is_422(self, client, auth):
        response = client.post(
            "/api/plan",
            data={"name": "t", "toml": "[steps.nonsense]\n"},
            content_type="application/json",
            **auth,
        )

        assert response.status_code == 422


@pytest.mark.django_db
class TestUnitIndex:
    def test_an_empty_step_is_an_empty_list(self, client, auth):
        response = client.get("/api/units?step=masks", **auth)

        assert response.json() == []

    def test_an_unknown_step_is_404(self, client, auth):
        response = client.get("/api/units?step=nonsense", **auth)

        assert response.status_code == 404

    def test_digests_agree_with_the_client_side_computation(self, client, auth):
        _post_unit(client, auth)
        payload = _unit_payload()
        expected = storage.unit_digest(
            (m["display"], m["slice"], m["digest"]) for m in payload["images"]
        )

        response = client.get("/api/units?step=masks", **auth)

        assert response.json() == [{"file1": payload["file1"], "unit_digest": expected}]


@pytest.mark.django_db
class TestPushUnit:
    def test_happy_path_creates_the_rows(self, client, auth):
        _post_unit(client, auth)

        assert Image.objects.count() == 2

    def test_happy_path_reports_created(self, client, auth):
        response = _post_unit(client, auth)

        assert response.json()["created"] is True

    def test_happy_path_stores_the_files(self, client, auth):
        _post_unit(client, auth)

        assert len(list(storage.stored_names())) == 2

    def test_the_stored_bytes_round_trip(self, client, auth):
        _post_unit(client, auth)
        image = Image.objects.get(display=DisplayMode.X)

        assert image.img.read() == AVIF

    def test_a_repushed_unit_adds_no_duplicate(self, client, auth):
        _post_unit(client, auth)

        _post_unit(client, auth)

        assert Image.objects.count() == 2

    def test_a_repushed_unit_reports_not_created(self, client, auth):
        _post_unit(client, auth)

        response = _post_unit(client, auth)

        assert response.json()["created"] is False

    def test_records_the_metrics(self, client, auth):
        _post_unit(client, auth)
        from django_dirt_ratings.models import Metric

        assert Metric.objects.get(name="mask_volume").value == 100.0

    def test_an_unknown_plan_hash_is_409(self, client, auth):
        response = _post_unit(client, auth, payload=_unit_payload(plan_hash="f" * 64))

        assert response.status_code == 409

    def test_a_known_plan_hash_is_stamped(self, client, auth):
        plan_hash = client.post(
            "/api/plan",
            data={"name": "t", "toml": PLAN_TOML},
            content_type="application/json",
            **auth,
        ).json()["content_hash"]

        _post_unit(client, auth, payload=_unit_payload(plan_hash=plan_hash))

        assert Image.objects.filter(review_plan=ReviewPlan.objects.get()).count() == 2

    def test_an_unknown_step_is_422(self, client, auth):
        response = _post_unit(client, auth, payload=_unit_payload(step="nonsense"))

        assert response.status_code == 422


@pytest.mark.django_db
class TestTarRefusals:
    """The wire format never trusts the sender (see transfer.py)."""

    def test_a_non_avif_member_is_415(self, client, auth):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        payload = _unit_payload(
            images=[{"display": 0, "slice": 0, "digest": transfer.content_digest(png)}]
        )

        response = _post_unit(client, auth, payload=payload, tar=_tar([(0, 0, png)]))

        assert response.status_code == 415

    def test_a_digest_mismatch_is_415(self, client, auth):
        payload = _unit_payload(images=[{"display": 0, "slice": 0, "digest": "0" * 16}])

        response = _post_unit(client, auth, payload=payload, tar=_tar([(0, 0, AVIF)]))

        assert response.status_code == 415

    def test_an_undeclared_view_is_415(self, client, auth):
        payload = _unit_payload(
            images=[{"display": 0, "slice": 0, "digest": transfer.content_digest(AVIF)}]
        )

        response = _post_unit(client, auth, payload=payload, tar=_tar([(2, 9, AVIF)]))

        assert response.status_code == 415

    def test_a_missing_declared_view_is_415(self, client, auth):
        response = _post_unit(client, auth, tar=_tar([(0, 0, AVIF)]))

        assert response.status_code == 415

    def test_a_non_regular_member_is_415(self, client, auth):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            link = tarfile.TarInfo("d0s0.avif")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)

        response = _post_unit(client, auth, tar=buffer.getvalue())

        assert response.status_code == 415

    def test_an_oversized_member_is_415(self, client, auth, settings):
        settings.INGEST_MAX_IMAGE_BYTES = 8
        response = _post_unit(client, auth)

        assert response.status_code == 415

    def test_an_oversized_tar_is_413(self, client, auth, settings):
        settings.INGEST_MAX_TAR_BYTES = 8

        response = _post_unit(client, auth)

        assert response.status_code == 413

    def test_a_refused_upload_writes_no_rows(self, client, auth):
        _post_unit(client, auth, tar=_tar([(0, 0, AVIF)]))

        assert Image.objects.count() == 0


@pytest.mark.django_db
class TestPrioritizeEndpoint:
    def test_responds_with_the_update_count(self, client, auth):
        response = client.post("/api/prioritize", **auth)

        assert response.json() == {"images_updated": 0}


@pytest.mark.django_db
class TestExports:
    @pytest.fixture
    def rated(self, fmap_image, fmap_session):
        return Rating.objects.create(
            image=fmap_image, session=fmap_session, rating=Ratings.PASS
        )

    def test_ratings_carry_the_image_identity(self, client, auth, rated):
        response = client.get("/api/ratings", **auth)

        assert response.json()[0]["file1"] == rated.image.file1

    def test_ratings_carry_the_session_user(self, client, auth, rated):
        response = client.get("/api/ratings", **auth)

        assert response.json()[0]["session_user"] is None

    def test_annotations_carry_their_cells(
        self, client, auth, mask_image, mask_session
    ):
        annotation = Annotation.objects.create(
            image=mask_image, session=mask_session, grid_cols=28, grid_rows=21
        )
        annotation.cells.create(col=1, row=2, rating=Ratings.FAIL)

        response = client.get("/api/annotations", **auth)

        assert response.json()[0]["cells"] == [{"col": 1, "row": 2, "rating": 2}]

    def test_ratings_require_credentials(self, client, ingest_enabled, rated):
        response = client.get("/api/ratings")

        assert response.status_code == 401
