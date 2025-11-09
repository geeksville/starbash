# Where should we write the GIF?
# command docs: https://github.com/charmbracelet/vhs?tab=readme-ov-file#vhs-command-reference
# FIXME - switch to using github actions to generate https://github.com/charmbracelet/vhs-action?tab=readme-ov-file
Output doc/vhs/process-siril.gif

Set Padding 6
Set BorderRadius 3
Set FontSize 20
Set Width 1200
Set Height 300
Set WindowBar Colorful
# Set TypingSpeed 0s

Require sb

Type "sb select list"
Sleep 0.5s
Enter
Sleep 2s

Type "sb process siril 3 ./siril-process"
Sleep 0.5s
Enter
Sleep 2s

Type "cd siril-process"
Sleep 0.5s
Enter
Type "ls -lR"
Sleep 0.5s
Enter
Sleep 2s