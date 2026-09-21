# Docs

Render the counter card and the packing list to PDF, and deliver them.

Invoke the `packing-docs` skill and follow it. Compile with Typst against the workspace YAML —
do not transcribe numbers into a `.typ` file by hand.

Check the delivery config at `~/.claude-plugins/travel-packing-assistant/delivery.yaml`. Default to
saving in `output/`. If the plan carries warnings, the documents render as PROVISIONAL — leave
that in.

`$ARGUMENTS` may name which document (`card`, `list`, or both) and a delivery override
(`--email`, `--drive`, `--local`).
