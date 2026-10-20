# ```bash
make test
make spec-test
make readme-check
# ```
#
# `make test`: pytest and ruff. `make spec-test`: requirement tests, red
# results are allowed. `make readme-check`: every README command in a
# throwaway container, sets the status lines, needs Docker.
