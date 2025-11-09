# Where should we write the GIF?
# command docs: https://github.com/charmbracelet/vhs?tab=readme-ov-file#vhs-command-reference
# FIXME - switch to using github actions to generate https://github.com/charmbracelet/vhs-action?tab=readme-ov-file
Output doc/vhs/sample-session.gif

Set Padding 6
Set BorderRadius 3
Set FontSize 20
Set Width 1200
Set Height 600
Set WindowBar Colorful

Require sb

Type "sb info"
Sleep 0.5s
Enter
Sleep 2s

Type "sb repo list"
Sleep 0.5s
Enter
Sleep 2s

Type "sb select target m20"
Sleep 0.5s
Enter
Sleep 2s