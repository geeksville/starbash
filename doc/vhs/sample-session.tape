# Where should we write the GIF?
# command docs: https://github.com/charmbracelet/vhs?tab=readme-ov-file#vhs-command-reference
# FIXME - switch to using github actions to generate https://github.com/charmbracelet/vhs-action?tab=readme-ov-file
Output doc/vhs/sample-session.gif

Set FontSize 20
Set Width 1200
Set Height 1000
Set WindowBar Colorful

Require sb

Type "sb"
Sleep 0.5s
Enter
Sleep 2s

Type "sb info"
Sleep 0.5s
Enter
Sleep 2s

Type "sb repo"
Sleep 0.5s
Enter
Sleep 2s

Type "sb select"
Sleep 0.5s
Enter
Sleep 2s