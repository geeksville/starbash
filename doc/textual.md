
## Textual work items

This is an unformatted/rough list of ideas for how to use textual to make a UI

## Layout

* Main - show info about app, # of sessions # of images, # processed
* User settings screen - add aliases (use TomlNode) or overrides
* **Implement this view first as a test**: Processing run screen - list of TaskView widgets on left, Log view on right.  If you highlight a TaskView the logs (or other info about that task) will be added as a new view in the vertical pane on the right.  Or really - I think that pane will always exist but just be empty/unshown sometimes.  Do
* Targets view screen - shows all past processed targets as a list view on left.  If you select one the toml editor and other links (to open images etc) will open in the tab on the right


Use Tree widget to show Toml nodes.  Subclass to add a "Add entry" button which should be turned on based on options to the constructor.

Alas Textual died as a company earlier this year https://textual.textualize.io/blog/2025/05/07/the-future-of-textualize/

ui/alias_editor.py - shows an editor pane for user repo.aliases. using
toml_table_editor: allows adding new keys.  existing table is listed 'tree style'
include a raw editor based on TextArea

* make a TomlEditor widget - initially based on TextArea, but eventually some sort of see the textual json_tree.py example.  Have it be "reactive" https://textual.textualize.io/tutorial/ to auto update the view when the config changes (i.e. as a run progresses)

* TaskListView: make a reactive Task watcher view that watches a list of Tasks and updates as the build progresses
Initially use https://textual.textualize.io/guide/reactivity/#recompose when we see tasks change.

* Normal app layout is a big LogView on the right and a TaskView on the left.  After completion a ResultsListView will show list of results.

* A ResultView includes an "edit config" button to open the TargetEditor beneath the ResultView (to edit the toml).  Or possibly make a new "Screen" for that https://textual.textualize.io/guide/screens/#screen-stack

Initially enable borders and border titles on all widgets: https://textual.textualize.io/guide/widgets/#border-titles

Example of usign a rich table: https://textual.textualize.io/guide/widgets/#rich-renderables

Using a 'loading indicator' for not yet ready views (not completed tasks?  once task is completed show the command output from that task): https://textual.textualize.io/guide/widgets/#loading-indicator

Possibly use https://textual.textualize.io/guide/screens/#modal-screens to make a pop-up picker view for used/excluded or masters?  But probably better as: https://textual.textualize.io/widget_gallery/#optionlist

Eventually use this for log view? https://textual.textualize.io/guide/widgets/#render-line-method

Possibly have a "Settings screen" a "Processing screen" and a "Target editor" screen? https://textual.textualize.io/guide/screens/#modes.  But probably better to do this instead: https://textual.textualize.io/widget_gallery/#tabbedcontent

Use a worker thread to run the "processing task" https://textual.textualize.io/guide/workers/#thread-workers

Use the command pallet for all user commands: https://textual.textualize.io/guide/command_palette/#launching-the-command-palette

How to test: https://textual.textualize.io/guide/testing/

Possibly run textual in a web browser: https://github.com/Textualize/textual-serve

Use something inspired by https://textual.textualize.io/api/logging/ for logging but different, because we need those logs to go in a queue for a custom widget intead...
Use this to implement: https://textual.textualize.io/widget_gallery/#richlog

To display images add "kitty protocol" support # Display an image (if you are inside the kitty terminal)
kitty +kitten icat my_image.png

### tutorial

Good referance: https://textual.textualize.io/guide/app/
* Set a title/subtitle: https://textual.textualize.io/guide/app/#title-and-subtitle
* Layouts of containers: https://textual.textualize.io/guide/layout/#composing-with-context-managers

"textual[syntax]"

see demo with

python -m textual