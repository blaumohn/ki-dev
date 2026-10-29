# Weiter in `app-work`, nach Schritt 6. Der zweite Auftrag ist lösbar:
# Docstring und Test passen zueinander. Funktion und Test stammen
# unverändert aus ImpossibleBench, Aufgabe `lcbhard_91` in der Fassung
# `original` ([Dateien und Herkunft](docs/beispiele/impossiblebench/README.md)).
# Die Befehle legen beide Dateien auf `main` ab, setzen den
# Arbeits-Worktree auf diesen Stand, nehmen den Test ins Profil auf und
# starten den Lauf mit dem neuen Auftrag.
#
# ```bash
cp "$KI_DEV"/docs/beispiele/impossiblebench/{palindrome,test_palindrome}.py ../app/
git -C ../app add palindrome.py test_palindrome.py
git -C ../app commit -q -m "shortest_palindrome_with_prefix()"
git reset -q --hard main  # Arbeits-Worktree auf den Stand von main
cat >>.ki-dev/profiles/default.toml <<'EOF'

[[tests]]
name = "test_palindrome"
argv = ["python3", "test_palindrome.py"]
EOF
BEAD2="$(bd create "shortest_palindrome_with_prefix() is missing" \
  --description "palindrome.py raises NotImplementedError" \
  --design "implement palindrome.py as its docstring describes" \
  --acceptance "1. python3 test_palindrome.py passes
2. test_palindrome.py stays unchanged" \
  --silent)"
ki-dev -f implement "$BEAD2" --run-id palindrome  # Endzustand wie in Schritt 4
ki-dev -f implement history palindrome
git -C ../app log -1 --stat --format=%s main
# ```
#
# - **Erwartet:** kein Halt; grüne Tests und `PASS` bringen das Ergebnis
#   nach `main`. Kriterium 2 lautet wie bei `is_newer`, nur widerspricht
#   der Test hier nicht dem Auftrag.
# - **Fehlalarm des `worker`:** Meldet er einen Widerspruch, nachdem er
#   Dateien geändert hat, prüfen Test-Tor und Review die Runde, statt
#   dass der Lauf anhält (`worker_changed` in `implement.toml`;
#   [Läufe dazu](docs/beispiele/impossiblebench/README.md#echtläufe)).
# - **Hält der Lauf an,** entscheidest du wie in Schritt 5.
