from django.dispatch import Signal

# Sent by `move()` and `force_move()` after the UPDATE changed the row, following `post_save`. Arguments: `sender` (the
# model class), `instance`, `field` (the phase field), `source` and `target` (stored values), `forced` (whether the
# transition table was bypassed), `reason` (given to `force_move()`, else `None`) and `using`.
phase_moved = Signal()

# Sent once by `move_many()` after it moved at least one row. Arguments: `sender` (the model of the queryset), `field`,
# `pks` (the primary keys of the moved rows), `source`, `target` and `using`.
phase_moved_many = Signal()
