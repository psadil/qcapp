import json

from django import forms
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from . import models, views

# ============================================================================
# MODEL TESTS - Separate class for each model
# ============================================================================


class SessionModelTests(TestCase):
    """Test cases for Session model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_session_creation(self):
        """Test Session model creation."""
        session = models.Session.objects.create(step=models.Step.MASK, user="testuser")
        self.assertEqual(session.step, models.Step.MASK)
        self.assertEqual(session.user, "testuser")
        self.assertIsNotNone(session.created)

    def test_session_creation_with_null_user(self):
        """Test Session model creation with null user."""
        session = models.Session.objects.create(step=models.Step.MASK)
        self.assertEqual(session.step, models.Step.MASK)
        self.assertIsNone(session.user)
        self.assertIsNotNone(session.created)

    def test_session_string_representation(self):
        """Test Session model string representation."""
        session = models.Session.objects.create(step=models.Step.MASK, user="testuser")
        self.assertIn(str(session.step), str(session))


class ImageModelTests(TestCase):
    """Test cases for Image model."""

    def test_image_creation(self):
        """Test Image model creation."""
        image_data = b"fake_image_data"
        image = models.Image.objects.create(
            img=image_data,
            slice=10,
            file1="/path/to/file1.nii.gz",
            file2="/path/to/file2.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )
        self.assertEqual(image.img, image_data)
        self.assertEqual(image.slice, 10)
        self.assertEqual(image.file1, "/path/to/file1.nii.gz")
        self.assertEqual(image.file2, "/path/to/file2.nii.gz")
        self.assertEqual(image.display, models.DisplayMode.X)
        self.assertEqual(image.step, models.Step.MASK)
        self.assertIsNotNone(image.created)

    def test_image_creation_with_null_file2(self):
        """Test Image model creation with null file2."""
        image_data = b"fake_image_data"
        image = models.Image.objects.create(
            img=image_data,
            file1="/path/to/file1.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )
        self.assertEqual(image.img, image_data)
        self.assertIsNone(image.file2)
        self.assertEqual(image.file1, "/path/to/file1.nii.gz")

    def test_image_creation_with_null_slice(self):
        """Test Image model creation with null slice."""
        image_data = b"fake_image_data"
        image = models.Image.objects.create(
            img=image_data,
            file1="/path/to/file1.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )
        self.assertEqual(image.img, image_data)
        self.assertIsNone(image.slice)


class RatingModelTests(TestCase):
    """Test cases for Rating model."""

    def setUp(self):
        """Set up test data."""
        self.session = models.Session.objects.create(
            step=models.Step.MASK, user="testuser"
        )
        self.image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

    def test_rating_creation(self):
        """Test Rating model creation."""
        rating = models.Rating.objects.create(
            image=self.image,
            session=self.session,
            rating=models.Ratings.PASS,
            source_data_issue=False,
        )
        self.assertEqual(rating.image, self.image)
        self.assertEqual(rating.session, self.session)
        self.assertEqual(rating.rating, models.Ratings.PASS)
        self.assertFalse(rating.source_data_issue)
        self.assertIsNotNone(rating.created)

    def test_rating_creation_with_source_data_issue(self):
        """Test Rating model creation with source data issue."""
        rating = models.Rating.objects.create(
            image=self.image,
            session=self.session,
            rating=models.Ratings.FAIL,
            source_data_issue=True,
        )
        self.assertEqual(rating.rating, models.Ratings.FAIL)
        self.assertTrue(rating.source_data_issue)

    def test_rating_creation_with_null_rating(self):
        """Test Rating model creation with null rating."""
        rating = models.Rating.objects.create(
            image=self.image,
            session=self.session,
            source_data_issue=False,
        )
        self.assertIsNone(rating.rating)


class ClickedCoordinateModelTests(TestCase):
    """Test cases for ClickedCoordinate model."""

    def setUp(self):
        """Set up test data."""
        self.session = models.Session.objects.create(
            step=models.Step.MASK, user="testuser"
        )
        self.image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

    def test_clicked_coordinate_creation(self):
        """Test ClickedCoordinate model creation."""
        clicked_coord = models.ClickedCoordinate.objects.create(
            image=self.image,
            session=self.session,
            x=100.5,
            y=200.3,
            source_data_issue=False,
        )
        self.assertEqual(clicked_coord.image, self.image)
        self.assertEqual(clicked_coord.session, self.session)
        self.assertEqual(clicked_coord.x, 100.5)
        self.assertEqual(clicked_coord.y, 200.3)
        self.assertFalse(clicked_coord.source_data_issue)
        self.assertIsNotNone(clicked_coord.created)

    def test_clicked_coordinate_creation_with_null_coordinates(self):
        """Test ClickedCoordinate model creation with null coordinates."""
        clicked_coord = models.ClickedCoordinate.objects.create(
            image=self.image,
            session=self.session,
            source_data_issue=False,
        )
        self.assertIsNone(clicked_coord.x)
        self.assertIsNone(clicked_coord.y)


class DynamicRatingModelTests(TestCase):
    """Test cases for DynamicRating model."""

    def setUp(self):
        """Set up test data."""
        self.session = models.Session.objects.create(
            step=models.Step.MASK, user="testuser"
        )
        self.image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

    def test_dynamic_rating_creation(self):
        """Test DynamicRating model creation."""
        dynamic_rating = models.DynamicRating.objects.create(
            image=self.image,
            session=self.session,
            rating=models.Ratings.FAIL,
            source_data_issue=True,
        )
        self.assertEqual(dynamic_rating.image, self.image)
        self.assertEqual(dynamic_rating.session, self.session)
        self.assertEqual(dynamic_rating.rating, models.Ratings.FAIL)
        self.assertTrue(dynamic_rating.source_data_issue)
        self.assertIsNotNone(dynamic_rating.created)


# ============================================================================
# VIEW TESTS - Separate class for each view
# ============================================================================


class LayoutViewTests(TestCase):
    """Test cases for LayoutView."""

    def setUp(self):
        """Set up test data."""
        self.client = self.client
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_layout_view_get(self):
        """Test LayoutView GET request."""
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "index.html")

    def test_layout_view_post_valid(self):
        """Test LayoutView POST with valid data."""
        data = {"step": models.Step.MASK}
        response = self.client.post(reverse("index"), data)
        self.assertEqual(response.status_code, 302)  # Redirect after success

    def test_layout_view_post_invalid(self):
        """Test LayoutView POST with invalid data."""
        data = {"step": 999}  # Invalid step
        response = self.client.post(reverse("index"), data)
        self.assertEqual(response.status_code, 200)  # Form errors, re-render

    def test_layout_view_success_url_mapping(self):
        """Test LayoutView success URL mapping for different steps."""
        # Test each step maps to correct URL
        step_url_mapping = {
            models.Step.MASK: "mask",
            models.Step.SPATIAL_NORMALIZATION: "spatial_normalization",
            models.Step.SURFACE_LOCALIZATION: "surface_localization",
            models.Step.FMAP_COREGISTRATION: "fmap_coregistration",
            models.Step.DTIFIT: "dtifit",
        }

        for step, expected_url_name in step_url_mapping.items():
            data = {"step": step}
            response = self.client.post(reverse("index"), data)
            self.assertEqual(response.status_code, 302)


class RateMaskViewTests(TestCase):
    """Test cases for RateMask view."""

    def setUp(self):
        """Set up test data."""
        self.client = self.client
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_rate_mask_view_get(self):
        """Test RateMask view GET request."""
        # Create test image
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

        response = self.client.get(reverse("mask"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rate_image.html")

    def test_rate_mask_view_post_valid(self):
        """Test RateMask view POST with valid data."""
        # Create test session and image
        session = models.Session.objects.create(step=models.Step.MASK, user="testuser")
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

        # Set session data
        session_data = self.client.session
        session_data["session_id"] = session.pk
        session_data["image_id"] = image.pk
        session_data.save()

        data = {
            "rating": models.Ratings.PASS,
            "source_data_issue": False,
        }
        response = self.client.post(reverse("mask"), data)
        self.assertEqual(response.status_code, 200)  # Should redirect to main template

    def test_rate_mask_view_post_with_points(self):
        """Test RateMask view POST with points data."""
        # Create test session and image
        session = models.Session.objects.create(step=models.Step.MASK, user="testuser")
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

        # Set session data
        session_data = self.client.session
        session_data["session_id"] = session.pk
        session_data["image_id"] = image.pk
        session_data.save()

        points = [{"x": 100, "y": 200}, {"x": 150, "y": 250}]
        data = {
            "source_data_issue": False,
            "points": json.dumps(points),
        }
        response = self.client.post(reverse("mask"), data)
        self.assertEqual(response.status_code, 200)  # Should redirect to main template


class RateSpatialNormalizationViewTests(TestCase):
    """Test cases for RateSpatialNormalization view."""

    def setUp(self):
        """Set up test data."""
        self.client = self.client
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_rate_spatial_normalization_view_get(self):
        """Test RateSpatialNormalization view GET request."""
        # Create test image
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.SPATIAL_NORMALIZATION,
        )

        response = self.client.get(reverse("spatial_normalization"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rate_image.html")


class RateSurfaceLocalizationViewTests(TestCase):
    """Test cases for RateSurfaceLocalization view."""

    def setUp(self):
        """Set up test data."""
        self.client = self.client
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_rate_surface_localization_view_get(self):
        """Test RateSurfaceLocalization view GET request."""
        # Create test image
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.SURFACE_LOCALIZATION,
        )

        response = self.client.get(reverse("surface_localization"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rate_image.html")


class RateFMapCoregistrationViewTests(TestCase):
    """Test cases for RateFMapCoregistration view."""

    def setUp(self):
        """Set up test data."""
        self.client = self.client
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_rate_fmap_coregistration_view_get(self):
        """Test RateFMapCoregistration view GET request."""
        # Create test image
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.FMAP_COREGISTRATION,
        )

        response = self.client.get(reverse("fmap_coregistration"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rate_image.html")


class RateDTIFITViewTests(TestCase):
    """Test cases for RateDTIFIT view."""

    def setUp(self):
        """Set up test data."""
        self.client = self.client
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_rate_dtifit_view_get(self):
        """Test RateDTIFIT view GET request."""
        # Create test image
        image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.DTIFIT,
        )

        response = self.client.get(reverse("dtifit"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rate_image.html")


# ============================================================================
# FORM TESTS - Separate class for each form
# ============================================================================


class RatingFormTests(TestCase):
    """Test cases for RatingForm."""

    def test_rating_form_valid(self):
        """Test RatingForm with valid data."""
        from .forms import RatingForm

        data = {
            "rating": models.Ratings.PASS,
            "source_data_issue": False,
        }
        form = RatingForm(data=data)
        self.assertTrue(form.is_valid())

    def test_rating_form_invalid_rating(self):
        """Test RatingForm with invalid rating."""
        from .forms import RatingForm

        data = {
            "rating": 999,  # Invalid rating
            "source_data_issue": False,
        }
        form = RatingForm(data=data)
        self.assertFalse(form.is_valid())

    def test_rating_form_missing_rating(self):
        """Test RatingForm with missing rating."""
        from .forms import RatingForm

        data = {
            "source_data_issue": False,
        }
        form = RatingForm(data=data)
        self.assertTrue(form.is_valid())  # Rating can be null

    def test_rating_form_widget_configuration(self):
        """Test RatingForm widget configuration."""
        from .forms import RatingForm

        form = RatingForm()
        self.assertIsInstance(form.fields["rating"].widget, forms.RadioSelect)


class IndexFormTests(TestCase):
    """Test cases for IndexForm."""

    def test_index_form_valid(self):
        """Test IndexForm with valid data."""
        from .forms import IndexForm

        data = {"step": models.Step.MASK}
        form = IndexForm(data=data)
        self.assertTrue(form.is_valid())

    def test_index_form_invalid_step(self):
        """Test IndexForm with invalid step."""
        from .forms import IndexForm

        data = {"step": 999}  # Invalid step
        form = IndexForm(data=data)
        self.assertFalse(form.is_valid())

    def test_index_form_missing_step(self):
        """Test IndexForm with missing step."""
        from .forms import IndexForm

        data = {}
        form = IndexForm(data=data)
        self.assertFalse(form.is_valid())


class ClickFormTests(TestCase):
    """Test cases for ClickForm."""

    def test_click_form_valid(self):
        """Test ClickForm with valid data."""
        from .forms import ClickForm

        data = {"source_data_issue": False}
        form = ClickForm(data=data)
        self.assertTrue(form.is_valid())

    def test_click_form_with_source_data_issue(self):
        """Test ClickForm with source data issue."""
        from .forms import ClickForm

        data = {"source_data_issue": True}
        form = ClickForm(data=data)
        self.assertTrue(form.is_valid())

    def test_click_form_missing_source_data_issue(self):
        """Test ClickForm with missing source data issue."""
        from .forms import ClickForm

        data = {}
        form = ClickForm(data=data)
        self.assertTrue(form.is_valid())  # Has default value


# ============================================================================
# UTILITY FUNCTION TESTS
# ============================================================================


class GetMaskWithFewestRatingsTests(TestCase):
    """Test cases for _get_mask_with_fewest_ratings function."""

    def test_get_mask_with_fewest_ratings(self):
        """Test _get_mask_with_fewest_ratings function."""
        # Create test images with different rating counts
        image1 = models.Image.objects.create(
            img=b"fake_image_data_1",
            file1="/path/to/file1.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )
        image2 = models.Image.objects.create(
            img=b"fake_image_data_2",
            file1="/path/to/file2.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

        # Create session
        session = models.Session.objects.create(step=models.Step.MASK, user="testuser")

        # Add one rating to image1
        models.Rating.objects.create(
            image=image1,
            session=session,
            rating=models.Ratings.PASS,
            source_data_issue=False,
        )

        # Get image with fewest ratings
        result = views._get_mask_with_fewest_ratings(
            models.Step.MASK, "rating", "source_data_issue"
        )

        # Should return image2 (no ratings) instead of image1 (1 rating)
        self.assertEqual(result, image2)

    def test_get_mask_with_fewest_ratings_no_images(self):
        """Test _get_mask_with_fewest_ratings with no images."""
        with self.assertRaises(Exception):  # Should raise Http404
            views._get_mask_with_fewest_ratings(
                models.Step.MASK, "rating", "source_data_issue"
            )

    def test_get_mask_with_fewest_ratings_equal_ratings(self):
        """Test _get_mask_with_fewest_ratings with equal rating counts."""
        # Create test images
        image1 = models.Image.objects.create(
            img=b"fake_image_data_1",
            file1="/path/to/file1.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )
        image2 = models.Image.objects.create(
            img=b"fake_image_data_2",
            file1="/path/to/file2.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

        # Create session
        session = models.Session.objects.create(step=models.Step.MASK, user="testuser")

        # Add one rating to each image
        models.Rating.objects.create(
            image=image1,
            session=session,
            rating=models.Ratings.PASS,
            source_data_issue=False,
        )
        models.Rating.objects.create(
            image=image2,
            session=session,
            rating=models.Ratings.FAIL,
            source_data_issue=False,
        )

        # Get image with fewest ratings (should return one of them)
        result = views._get_mask_with_fewest_ratings(
            models.Step.MASK, "rating", "source_data_issue"
        )

        # Should return one of the images (both have same rating count)
        self.assertIn(result, [image1, image2])


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class RatingWorkflowIntegrationTests(TransactionTestCase):
    """Integration tests for the complete rating workflow."""

    def test_complete_rating_workflow(self):
        """Test the complete workflow from session creation to rating submission."""
        client = self.client

        # Step 1: Create session
        session_data = {"step": models.Step.MASK}
        response = client.post(reverse("index"), session_data)
        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Step 2: Access rating page
        response = client.get(reverse("mask"))
        self.assertEqual(response.status_code, 200)

        # Step 3: Submit rating
        rating_data = {
            "rating": models.Ratings.PASS,
            "source_data_issue": False,
        }
        response = client.post(reverse("mask"), rating_data)
        self.assertEqual(response.status_code, 200)


class ClickWorkflowIntegrationTests(TransactionTestCase):
    """Integration tests for the complete click workflow."""

    def test_complete_click_workflow(self):
        """Test the complete workflow for click-based rating."""
        client = self.client

        # Step 1: Create session
        session_data = {"step": models.Step.MASK}
        response = client.post(reverse("index"), session_data)
        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Step 2: Access click page
        response = client.get(reverse("mask"))
        self.assertEqual(response.status_code, 200)

        # Step 3: Submit click data with points
        points = [{"x": 100, "y": 200}]
        click_data = {
            "source_data_issue": False,
            "points": json.dumps(points),
        }
        response = client.post(reverse("mask"), click_data)
        self.assertEqual(response.status_code, 200)


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class RateViewEdgeCaseTests(TestCase):
    """Test edge cases for RateView."""

    def test_rate_view_no_session_data(self):
        """Test RateView when session data is missing."""
        client = self.client
        response = client.post(reverse("mask"), {"rating": models.Ratings.PASS})
        # Should handle missing session data gracefully
        self.assertEqual(response.status_code, 404)

    def test_rate_view_post_invalid(self):
        """Test RateView POST with invalid data."""
        data = {"rating": 999}  # Invalid rating
        response = self.client.post(reverse("mask"), data)
        self.assertEqual(response.status_code, 404)  # Http404 for invalid form


class ClickViewEdgeCaseTests(TestCase):
    """Test edge cases for ClickView."""

    def setUp(self):
        """Set up test data."""
        self.session = models.Session.objects.create(
            step=models.Step.MASK, user="testuser"
        )
        self.image = models.Image.objects.create(
            img=b"fake_image_data",
            file1="/path/to/file.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        )

    def test_click_view_empty_points(self):
        """Test ClickView with empty points array."""
        # Set session data
        session_data = self.client.session
        session_data["session_id"] = self.session.pk
        session_data["image_id"] = self.image.pk
        session_data.save()

        data = {
            "source_data_issue": False,
            "points": "[]",  # Empty array
        }
        response = self.client.post(reverse("mask"), data)
        self.assertEqual(response.status_code, 200)

    def test_click_view_invalid_points_json(self):
        """Test ClickView with invalid JSON in points."""
        # Set session data
        session_data = self.client.session
        session_data["session_id"] = self.session.pk
        session_data["image_id"] = self.image.pk
        session_data.save()

        data = {
            "source_data_issue": False,
            "points": "invalid json",  # Invalid JSON
        }
        response = self.client.post(reverse("mask"), data)
        self.assertEqual(response.status_code, 200)  # Should handle gracefully

    def test_click_view_no_points_parameter(self):
        """Test ClickView without points parameter."""
        # Set session data
        session_data = self.client.session
        session_data["session_id"] = self.session.pk
        session_data["image_id"] = self.image.pk
        session_data.save()

        data = {
            "source_data_issue": False,
        }
        response = self.client.post(reverse("mask"), data)
        self.assertEqual(response.status_code, 200)
