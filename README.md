# QCAPP <a href="https://github.com/psadil/qcapp"><img src="qcapp/static/qcapp/qcapp.png" align="right" height="138" /></a>

## Running

Note that the following assumes existence of a file `.env` with a value for the variable `DJANGO_SECRET_KEY`, and the variable `DB` set to `/tmp/db.sqlite3`.

```shell
# assumes existence of a database db.sqlite3
db=$PWD/db.sqlite3
docker run \
  --rm \  
  -v ${db}:/tmp/db.sqlite3 \
  --env-file=.env \
  -p 8000:8000 \
  psadil/qcapp
```

If all goes well, you should see output like this

```shell
2025-06-16 21:47:44,039 | INFO     | Watching for file changes with StatReloader
Performing system checks...

System check identified no issues (0 silenced).
June 16, 2025 - 21:47:44
Django version 5.2.3, using settings 'qcapp.settings'
Starting ASGI/Daphne version 4.2.0 development server at http://0.0.0.0:8000/
Quit the server with CONTROL-C.
2025-06-16 21:47:44,076 | INFO     | HTTP/2 support enabled
2025-06-16 21:47:44,076 | INFO     | Configuring endpoint tcp:port=8000:interface=0.0.0.0
2025-06-16 21:47:44,076 | INFO     | Listening on TCP address 0.0.0.0:8000
```

You should now be able to navigate to the app on a browser on your local machine: `http://localhost:8000`.

Select a processing step, and go rate! The rating are saved as you go along, so you can exit at any time.

## Tips

### sqlite3

#### Check tables

```shell
$ sqlite3 db.sqlite3 .tables;
auth_group                  django_content_type       
auth_group_permissions      django_migrations         
auth_permission             django_session            
auth_user                   ratings_layout            
auth_user_groups            ratings_mask              
auth_user_user_permissions  ratings_maskrating        
django_admin_log            ratings_rating   
```

#### Get All Ratings

```shell
$ sqlite3 -header db.sqlite3 "SELECT * FROM ratings_maskrating;"
id|img_id|mask_id|rating_id
1|188|1|1
2|165|7|2
```

#### Get All Ratings and Metadata

```shell
$ sqlite3 -header db.sqlite3 "SELECT mask, user, rating, created FROM ratings_maskrating LEFT JOIN ratings_mask ON ratings_maskrating.mask_id = ratings_mask.id LEFT JOIN ratings_rating ON ratings_maskrating.rating_id = ratings_rating.id;"
mask|user|rating|created
/Users/psadil/git/a2cps/biomarkers/tests/data/fmriprep2/sub-travel2/ses-RU/anat/sub-travel2_ses-RU_space-MNI152NLin2009cAsym_desc-brain_mask.nii.gz|psadil|0|2025-02-25 17:06:32.356821
/data/sub-travel2/ses-RU/anat/sub-travel2_ses-RU_space-MNI152NLin6Asym_desc-brain_mask.nii.gz|psadil|0|2025-02-25 23:46:44.217029
```

#### Get All Ratings and Metadata, with Extra Formatting

```shell
$ sqlite3 \
  -header \
  -json db.sqlite3 \
  "SELECT mask, user, rating, created FROM ratings_maskrating LEFT JOIN ratings_mask ON ratings_maskrating.mask_id = ratings_mask.id LEFT JOIN ratings_rating ON ratings_maskrating.rating_id = ratings_rating.id;" \
  | jq
```

```json
[
  {
    "mask": "/Users/psadil/git/a2cps/biomarkers/tests/data/fmriprep2/sub-travel2/ses-RU/anat/sub-travel2_ses-RU_space-MNI152NLin2009cAsym_desc-brain_mask.nii.gz",
    "user": "psadil",
    "rating": 0,
    "created": "2025-02-25 17:06:32.356821"
  },
  {
    "mask": "/data/sub-travel2/ses-RU/anat/sub-travel2_ses-RU_space-MNI152NLin6Asym_desc-brain_mask.nii.gz",
    "user": "psadil",
    "rating": 0,
    "created": "2025-02-25 23:46:44.217029"
  }
]
```

## Build

```shell
docker build -t psadil/qcapp --provenance=true --push .
```

Note that we're not pushing this to dockerhub. Everything will be run locally.
