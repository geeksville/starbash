as seen in private/processed/sh291
my hack for now is to exclude the 2026-08-09 and 2026-08-10 sessions
i did this by renaming to private/from_astroboy/Sh2 91/2026-08-08.sbignore because disabling the session
lights-vs-bias exposed a different bug


tip from rc astro

Mosaics
When assembling mosaics it is usual for any optical aberrations to be mismatched between frames in the corners and along edges. The top-right corner for one frame is the top-left corner for the next, so the aberrations will generally be different. A good approach is to apply BlurXTerminator in Correct Only mode on each mosaic frame prior to assembly, and then again on the assembled mosaic with any desired sharpening settings.

BlurXTerminator was trained to maintain optical centering of aberrated point spread functions during correction. Plate solving algorithms, on the other hand, generally do not comprehend aberrated PSFs. This can cause small errors in the plate solution, particularly when it comes to distortion calculations. For best accuracy during mosaic assembly, it may be a good idea to plate solve the individual frames again after correcting aberrations using BlurXTerminator’s Correct Only mode.

Putting all of this together into a workflow, starting from individual mosaic frames, might look like this:

Perform channel combination for each mosaic frame
Remove any gradients from each frame using your preferred method
Apply BlurXTerminator in Correct Only mode to each color mosaic frame
Run ImageSolver on each corrected frame to extract accurate coordinates and distortion parameters
Assemble the full mosaic using a photometrically accurate method
Run ImageSolver on the full mosaic
Perform precision color calibration (e.g., SPCC) on the full mosaic
Apply BlurXTerminator to the full mosaic with any desired sharpening settings