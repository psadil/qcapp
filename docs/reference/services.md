# Services (write side)

The write side of the app: every function here validates with `full_clean` and is the only
layer that creates or updates rows (see the [Django Styleguide](https://github.com/HackSoftware/Django-Styleguide)).

::: django_dirt_ratings.services
