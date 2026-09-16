"""End-to-end GUI tests: drive the real ``sb gui`` app and record it to a movie.

Unlike ``tests/unit/test_gui.py`` (which builds pieces of the GUI offscreen), this suite
plays a whole user journey through the real widgets - setup wizard, first run, processing -
and records it to an mp4 so the result can be *watched* rather than inferred. It is
deselected by default: see ``doc/plans/gui-integration-video.md``.

``qtmovie.py`` (the recorder) lives here rather than in ``src/``: nothing in the shipped
package records video. It is unit-tested in ``tests/unit/test_qtmovie.py``. ``driver.py``
(pump/click/type + the modal-wizard driver) is unit-tested in
``tests/unit/test_gui_integration_driver.py``.

Run it with ``just test-integration-gui`` (which then opens the movie), or directly::

    poetry run pytest tests/gui_integration -m gui_integration

$STARBASH_GUI_MOVIE chooses the output file (default /tmp/gui.mp4),
$GUI_MOVIE_TEST_DATA the dataset (default /test-data/asiair - the one-target set the run
processes; /test-data is every target and takes far longer), and $STARBASH_GUI_MOVIE_FAST
makes each scripted pause shorter while iterating on a script.
"""
