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
auth_group                  django_migrations         
auth_group_permissions      django_session            
auth_permission             ratings_clickedcoordinate 
auth_user                   ratings_dynamicrating     
auth_user_groups            ratings_image             
auth_user_user_permissions  ratings_rating            
django_admin_log            ratings_session           
django_content_type
```

#### Look through some basic ratings

```shell
$ sqlite3 -header db.sqlite3 "SELECT * FROM ratings_rating LIMIT 10;"
id|rating|source_data_issue|created|session_id|image_id
1|0|0|2025-04-05 22:28:04.244189|1|1
2|0|0|2025-04-05 22:28:07.492339|1|2
3|0|0|2025-04-05 22:28:20.364032|1|2542
4|0|1|2025-04-05 22:28:25.293246|1|2543
5|0|0|2025-04-05 22:28:28.736210|1|2544
6|0|0|2025-04-08 15:09:23.584500|1|2548
7|0|0|2025-04-08 15:09:27.203768|1|2549
8|0|0|2025-04-08 15:09:30.206838|1|2550
9|0|0|2025-04-08 15:09:33.375856|1|2551
10|0|0|2025-04-08 15:09:38.637260|1|2552
```

#### Look through location ratings

```shell
$ sqlite3 -header db.sqlite3 "SELECT * FROM ratings_clickedcoordinate LIMIT 10;"
id|source_data_issue|created|x|image_id|session_id|y
1|0|2025-04-08 21:14:14.250115|242.0|5|24|186.0
2|0|2025-04-08 21:14:14.250183|325.0|5|24|175.0
3|0|2025-04-08 21:14:14.250218|375.0|5|24|232.0
4|0|2025-04-08 21:17:23.721516|369.0|5|25|173.0
5|0|2025-04-08 21:17:23.721566|247.0|5|25|233.0
6|0|2025-04-08 21:17:23.721596|213.0|5|25|204.0
7|0|2025-04-08 21:18:02.419230|237.0|5|26|194.0
8|0|2025-04-08 21:18:02.419273|303.0|5|26|186.0
9|0|2025-04-08 21:18:02.419287|362.0|5|26|157.0
10|0|2025-04-08 21:21:42.424830|230.0|5|30|172.0
```

#### Get Ratings and Metadata

```shell
$ sqlite3 -header db.sqlite3 "SELECT rating, file1 FROM ratings_rating LEFT JOIN ratings_image ON ratings_rating.image_id = ratings_image.id LIMIT 20;"
rating|file1
0|sub-10003_ses-V1_desc-brain_mask.nii.gz
0|sub-10003_ses-V1_desc-brain_mask.nii.gz
0|sub-travel2_ses-RU_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
0|sub-travel2_ses-RU_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
0|sub-travel2_ses-RU_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
0|mri/brain.mgz
0|mri/brain.mgz
0|mri/brain.mgz
0|mri/brain.mgz
0|mri/brain.mgz
0|mri/brain.mgz
0|sub-travel2_ses-RU_acq-fmrib0_fmapid-auto00001_desc-epi_fieldmap.nii.gz
0|sub-travel2_ses-RU_acq-fmrib0_fmapid-auto00001_desc-epi_fieldmap.nii.gz
0|sub-10003_ses-V1_desc-brain_mask.nii.gz
0|sub-10003_ses-V1_desc-brain_mask.nii.gz
2|sub-travel2_ses-RU_space-MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz
0|sub-travel2_ses-RU_acq-fmrib0_fmapid-auto00001_desc-epi_fieldmap.nii.gz
```

## Build

```shell
docker build -t psadil/qcapp --provenance=true --push .
```

Note that we're not pushing this to dockerhub. Everything will be run locally.
