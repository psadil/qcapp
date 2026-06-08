#!/bin/bash
set -euo pipefail

# Ensure we're in the project root
PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

DATA_DIR="data/ds007070-fmriprep"
INDEX_FILE="data/ds007070_index.parquet"

echo "Downloading sample data from OpenNeuro (ds007070)..."
mkdir -p "$DATA_DIR"

for SUB in "sub-0001" "sub-0002"; do
    # anat files
    aws s3 sync --no-sign-request "s3://openneuro.org/ds007070/$SUB/ses-01/anat/" "$DATA_DIR/$SUB/ses-01/anat/" --exclude "*" --include "*desc-brain_mask.nii.gz" --include "*desc-preproc_T1w.nii.gz" --include "*.json"
    
    # func files needed for fmap coregistration
    aws s3 sync --no-sign-request "s3://openneuro.org/ds007070/$SUB/ses-01/func/" "$DATA_DIR/$SUB/ses-01/func/" --exclude "*" --include "*desc-brain_mask.nii.gz" --include "*desc-coreg_boldref.nii.gz" --include "*from-boldref_to-*_mode-image_xfm.txt" --include "*.json"
    
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
}' > "$DATA_DIR/dataset_description.json"

echo "Indexing dataset with bids2table..."
pixi run -e manage b2t2 index --output "$INDEX_FILE" --workers 2 "$DATA_DIR"

echo "Applying database migrations..."
# Set up env vars for local sqlite
export DB="${PROJECT_ROOT}/db.sqlite3"
export DJANGO_DEBUG=True
export DJANGO_SECRET_KEY='dev-secret-key-do-not-u1se-in-prod'

pixi run -e manage manage migrate

echo "Creating superuser (admin / admin)..."
# Create superuser if it doesn't exist
pixi run -e manage manage shell -c "
from django.contrib.auth import get_user_model;
User = get_user_model();
User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin', 'admin@example.com', 'admin')
"

echo "Populating database with images (this may take a minute)..."
echo "  -> Adding masks..."
pixi run -e manage manage add_masks "$INDEX_FILE"

echo "  -> Adding spatial normalization..."
pixi run -e manage manage add_spatial_normalization "$INDEX_FILE" --res 2

echo "  -> Adding surface localization..."
pixi run -e manage manage add_surface_localization "$DATA_DIR/sourcedata/freesurfer"

echo "  -> Adding fmap coregistration..."
pixi run -e manage manage add_fmap_coregistration "$INDEX_FILE"

echo ""
echo "Setup complete! You can now run the development server using Docker:"
echo "  docker buildx build -t psadil/dirt --platform=linux/amd64 --provenance=true ."
echo "  docker run --rm -it -v \$PWD/db.sqlite3:/tmp/db.sqlite3 --env-file=.env.docker -p 8000:8000 psadil/dirt"
echo ""
echo "Log in at http://localhost:8000/admin/ with username: admin, password: admin"
