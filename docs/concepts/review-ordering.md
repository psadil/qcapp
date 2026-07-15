# Review ordering

At consortium scale there are far more images than any one session can review, so the order
in which images are served matters. DIRT uses a **breadth-first** strategy: the next image
to show is the one that has been reviewed the fewest times.

## Why breadth-first

Spreading effort across the whole dataset first — one look at everything before a second
look at anything — surfaces clear-cut failures quickly and gives an early, unbiased sense
of overall dataset quality. As time allows, review naturally deepens: once every image has
one rating, the algorithm moves on to second ratings, and so on.

## How it is computed

The selector `image_with_fewest_ratings` returns, for a given processing step, the image
with the lowest review count (ties broken deterministically). Each image carries a
denormalized `n_reviews` counter, maintained as ratings come in, and a covering index on
`(step, n_reviews, id)`, so choosing the next image is a single index seek — fast enough to
serve synchronously on every transition.

!!! note "Toward a smarter selector"
    The grant vision for DIRT ("QCAPP") is a time-budgeted, sequential-learning selector:
    the reviewer states how long they have, and the app prioritizes images most likely to
    show clear failures before spending the remaining budget on subtle cases. The current
    breadth-first ordering is the deterministic seed for that future work.
