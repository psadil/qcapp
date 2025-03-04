# QCAPP

## Build

```shell
$ docker build -t psadil/qcapp --provenance=true --platform=linux/amd64 --push .
```

## Using the App

Start interactive job

```shell
# on TACC login node
idev -m 30 -p corralextra-dev
```

Note that the following assumes that you have a file `.env` with values for the variables `DJANGO_SECRET_KEY` and `DB`.

```shell
torate=/corral-secure/projects/A2CPS/shared/psadil/jobs/agg_with_skull/layout_masks
db=/corral-secure/projects/A2CPS/shared/psadil/qclog/derivatives/db.sqlite3
cd $(dirname $torate)
apptainer run \
  --bind ${torate} \
  --bind ${db}:/tmp/db.sqlite3 \
  --bind /corral-secure/projects/A2CPS \
  --env-file=.env \
  docker://psadil/qcapp
```
If all goes well, you shoudl see this output

```shell
Watching for file changes with StatReloader
Performing system checks...

System check identified no issues (0 silenced).
February 25, 2025 - 23:39:13
Django version 5.1.6, using settings 'qcapp.settings'
Starting development server at http://127.0.0.1:8000/
Quit the server with CONTROL-C.
```

Now, back on your machine, create a new `ssh` connection to the relevant system, forwarding ports.

```shell
ssh -L 8000:localhost:8000 ${USER}@login3.ls6.tacc.utexas.edu
```

Now that you're on the execution system, check which node is running the interactive job

```shell
$ squeue --me
JOBID    PARTITION                             NAME     USER    STATE         SUBMIT_TIME       TIME TIME_LIMI NODE NODELIST(REASON)
2236197     vm-small                         idv84398   psadil  RUNNING 2025-02-25T17:33:35       9:07     30:00    1 v320-003
```

`ssh` to that node, forwarding the ports again.

```shell
ssh -L 8000:localhost:8000 v320-003
```

If all goes well, you should now be able to navigate to the app on a browser on your local machine: `http://localhost:8000/ratings`.

You'll see a section to input the BIDS `Src`, which you should will with the path you mounted the folder pointed to by `${torate}` in `apptainer run` call (e.g., above, we had `--bind ${torate}`, and so you'd write the value of `torate`, which is `/corral-secure/projects/A2CPS/shared/psadil/jobs/agg_with_skull/layout_masks`, in the `Src` box).

The rating are saved as you go along, so you can exit at any time.

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

