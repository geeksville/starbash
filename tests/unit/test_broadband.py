"""Tests for stacking broadband lights onto a narrowband plate."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from astropy.io import fits

from starbash.doit import FileInfo
from starbash.fits import read_dimensions
from starbash.processing import Processing
from starbash.recipes import osc
from starbash.stages import select_stages, sort_stages
from starbash.tool import tools
from starbash.tool.context import expand_context_unsafe
from starbash.tool.siril import siril_line


def _load(name: str) -> Any:
    import tomlkit

    path = Path(__file__).parents[2] / "starbash-recipes" / name
    return tomlkit.parse(path.read_text())


class TestRegisterAndStackCommands:
    """The shared command builder, and the options stack_osc must keep."""

    def test_two_pass_is_the_default(self):
        commands = osc.register_and_stack_commands("osc", "results")

        assert "register osc -2pass" in commands
        assert "setref" not in commands
        assert "seqapplyreg osc  -framing=cog" in commands
        assert "stack r_osc rej w 3 3 -norm=addscale -output_norm -32b  -out=results" in commands
        assert "mirrorx_single results" in commands

    def test_stack_osc_options_reproduce_its_script(self):
        """Extracting the helper must not change what stack_osc asks Siril to do."""
        recipe = _load("osc/stack_osc.toml")["stages"][0]
        defaults = {item["name"]: item["default"] for item in recipe["parameters"]}
        commands = osc.register_and_stack_commands(
            "osc",
            "results",
            drizzle=str(defaults["drizzle"]),
            framing=str(defaults["framing"]),
            filtering=str(defaults["filtering"]),
            rejection=str(defaults["registration"]),
            stack_options=str(defaults["options"]),
        )

        assert (
            f"seqapplyreg osc {defaults['drizzle']} -framing={defaults['framing']} "
            f"{defaults['filtering']}"
        ) in commands
        assert (
            f"stack r_osc {defaults['registration']} {defaults['options']}  -out=results"
        ) in commands
        assert "setref" not in commands

    def test_reference_is_one_based_and_replaces_two_pass(self):
        commands = osc.register_and_stack_commands(
            "bb", "bb_stack", reference_index=90, stack_filter="-filter-included"
        )

        assert "register bb -noclamp" in commands
        assert commands.index("setref bb 90") < commands.index("register bb -noclamp")
        assert commands.index("unselect bb 90 90") > commands.index("register bb -noclamp")
        assert "register bb -2pass" not in commands
        assert "-filter-included" in commands.split("stack", 1)[1]

    def test_rejects_a_zero_based_reference_before_any_command(self):
        with pytest.raises(ValueError, match="start at 1"):
            osc.register_and_stack_commands("bb", "bb_stack", reference_index=0)


class TestBroadbandStackCommands:
    def test_plate_joins_before_it_is_pinned_and_is_not_stacked(self, tmp_path: Path):
        plate = tmp_path / "stacked_Ha.fits"
        plate.write_bytes(b"not read by the command builder")
        register, apply, stack = osc.broadband_stack_commands(
            "bb", 89, plate, tmp_path, tmp_path / "stacked_bb.fits"
        )
        commands = register + apply + stack

        # 89 lights, so the appended plate is Siril member 90, not 89.
        assert commands.index("convert bb -out=.") < commands.index("setref bb 90")
        assert commands.index("setref bb 90") < commands.index("register bb -noclamp")
        assert commands.index("register bb -noclamp") < commands.index("unselect bb 90 90")
        assert commands.index("unselect bb 90 90") < commands.rindex("setref bb 90")
        assert commands.rindex("setref bb 90") < commands.index("seqapplyreg bb")
        assert commands.index("seqapplyreg bb") < commands.index("stack r_bb")
        assert "unselect r_bb" not in commands
        assert "register bb -2pass" not in commands
        assert "-drizzle" not in commands
        assert "-framing=cog" in commands
        assert "-filter-included" in commands
        assert commands.count("setref bb 90") == 2

    def test_applied_index_is_the_row_not_the_file_number(self, tmp_path: Path):
        sequence = tmp_path / "r_bb_.seq"
        sequence.write_text("S 'r_bb_' 22 47 47\nI 22 1\nI 23 1\nI 90 1\n")
        assert osc.applied_member_index(sequence, 90) == 3

    def test_missing_applied_member_is_reported(self, tmp_path: Path):
        sequence = tmp_path / "r_bb_.seq"
        sequence.write_text("I 22 1\n")
        with pytest.raises(ValueError, match="has no image 90"):
            osc.applied_member_index(sequence, 90)

    def test_empty_sequence_never_builds_a_reference(self, tmp_path: Path):
        with pytest.raises(ValueError, match="no frames"):
            osc.broadband_stack_commands(
                "bb", 0, tmp_path / "plate.fits", tmp_path, tmp_path / "out.fits"
            )


class TestBroadbandWorkDirectory:
    def test_convert_sees_only_the_selected_sequence(self, tmp_path: Path):
        """A shared process directory must not become part of the sequence.

        ``convert`` reads every FITS file in its working directory. On a mixed
        target that directory holds every night, and the real run turned 89 Tri
        frames into 4832.
        """
        shared = tmp_path / "process"
        shared.mkdir()
        sequence = shared / "bkg_pp_light_s233_.seq"
        sequence.write_text("S 'bkg_pp_light_s233_' 1 1 1 5 -1 6 0 0 0\n")
        (shared / "bkg_pp_light_s233_00001.fit").write_bytes(b"tri")
        (shared / "bkg_pp_light_s225_00001.fit").write_bytes(b"duo")
        plate = tmp_path / "stacked_Ha.fits"
        plate.write_bytes(b"plate")

        work, name, count = osc._prepare_broadband_sequence(sequence, plate)

        assert name == "bkg_pp_light_s233"
        assert count == 1
        assert work == shared / "broadband"
        assert sorted(path.name for path in work.iterdir()) == [
            "bkg_pp_light_s233_00001.fit",
            "bkg_pp_light_s233_00002.fit",
        ]
        assert (work / "bkg_pp_light_s233_00002.fit").read_bytes() == b"plate"
        assert sequence.read_text().startswith("S ")

    def test_a_rewritten_header_does_not_copy_the_larger_set(self, tmp_path: Path):
        """The .seq header can claim frames that are dangling links.

        The failed broadband convert rewrote ``bkg_pp_light_s233_.seq`` to 4832
        and left ``.fits`` links beside the original ``.fit`` members. Copying
        by that count dies on the first broken link.
        """
        shared = tmp_path / "process"
        shared.mkdir()
        sequence = shared / "bkg_pp_light_s233_.seq"
        sequence.write_text("S 'bkg_pp_light_s233_' 1 4 4 5 -1 6 0 0 0\n")
        (shared / "bkg_pp_light_s233_00001.fit").write_bytes(b"tri")
        (shared / "bkg_pp_light_s233_00002.fit").write_bytes(b"tri")
        for index in range(1, 5):
            link = shared / f"bkg_pp_light_s233_{index:05d}.fits"
            link.symlink_to(shared / "missing.fits")
        plate = tmp_path / "stacked_Ha.fits"
        plate.write_bytes(b"plate")

        work, _, count = osc._prepare_broadband_sequence(sequence, plate)

        assert count == 2
        assert sorted(path.name for path in work.iterdir()) == [
            "bkg_pp_light_s233_00001.fit",
            "bkg_pp_light_s233_00002.fit",
            "bkg_pp_light_s233_00003.fit",
        ]
        assert (work / "bkg_pp_light_s233_00003.fit").read_bytes() == b"plate"


class TestReferenceShape:
    def test_rejects_a_resized_reference_without_saving(self, tmp_path: Path):
        plate = tmp_path / "stacked_Ha.fits"
        applied = tmp_path / "r_bb_00090.fit"
        fits.PrimaryHDU(data=[[0.0, 1.0], [0.0, 1.0]]).writeto(plate)
        fits.PrimaryHDU(data=[[0.0, 1.0, 2.0]]).writeto(applied)

        with pytest.raises(ValueError, match="3x1.*2x2"):
            osc.assert_reference_kept_shape(plate, applied)


def _prior(
    stage: str,
    name: str,
    path: str,
    metadata: dict | None = None,
    session_id: int | None = None,
) -> dict:
    return {
        "name": name,
        "meta": {
            "stage": {"name": stage},
            "context": {
                "session": {"id": session_id} if session_id is not None else {},
                "default_metadata": metadata or {},
                "input": {
                    0: FileInfo(image_rows=[{"abspath": f"/tmp/in_{path}", "path": f"in_{path}"}])
                },
                "output": FileInfo(
                    base="/tmp", image_rows=[{"abspath": f"/tmp/{path}", "path": path}]
                ),
            },
        },
    }


class TestStackBroadbandInputs:
    """The stage is skipped unless both a plate and a broadband sequence exist."""

    def setup_method(self):
        self.stage = _load("osc/stack_broadband.toml")["stages"][0]
        self.inputs = {item["name"]: item for item in self.stage["inputs"]}

    def _import(self, name: str, tasks: list[dict]):
        processing = Processing.__new__(Processing)
        processing.stage = {"inputs": [{"after": "upstream"}]}
        processing.processed_target = None
        processing.context = {"default_metadata": {}}
        processing._built_tasks = []
        processing._get_prior_tasks = lambda stage, input=None: tasks
        return processing._import_from_prior_stages(self.inputs[name])

    def test_recipe_is_registered_and_does_not_join_the_stack_role(self):
        manifest = _load("starbash.toml")
        refs = [ref.get("dir") for ref in manifest["repo-ref"]]
        assert refs.index("osc/stack_dual_duo.toml") < refs.index("osc/stack_broadband.toml")

        assert "role" not in self.stage
        assert self.stage["tool"]["name"] == "python"
        assert list(self.stage["outputs"][0]["name"]) == ["stacked_bb.fits"]
        assert self.inputs["lights"]["merge_to"] == "bb"
        assert self.inputs["lights"]["after"] == "(?:seqextract_haoiii|light.*)"
        assert self.inputs["ha"]["after"] == "stack_(dual_duo|single_duo|osc)"
        assert "duo" not in self.inputs
        # Joining the stack role would make select_stages drop this stage.
        catalog = [_load("osc/stack_dual_duo.toml")["stages"][0], self.stage]
        selected = select_stages(catalog)
        assert {stage["name"] for stage in selected.stages} == {"stack_dual_duo", "stack_broadband"}

    def test_each_input_follows_its_own_producer(self):
        """The plate and the lights come from different stages.

        ``_import_from_prior_stages`` used to follow the stage's first ``after``
        for every block. The plate is first, so the lights filter then ran against
        ``stacked_Ha.fits`` and the stage was skipped on a real mixed target.
        """
        plate = _prior("stack_dual_duo", "stack", "stacked_Ha.fits")
        lights = _prior("light_vs_dark", "light_s233", "bkg_pp_light_s233_.seq")
        processing = Processing.__new__(Processing)
        processing.stage = self.stage
        processing.processed_target = None
        processing.context = {"default_metadata": {}}
        processing._built_tasks = []
        processing._get_prior_tasks = lambda stage, input=None: (
            [lights] if input is not None and input.get("name") == "lights" else [plate]
        )

        imported = processing._import_from_prior_stages(self.inputs["lights"])

        assert imported.image_rows is not None
        assert [row["path"] for row in imported.image_rows] == ["bkg_pp_light_s233_.seq"]

    def test_tri_sequence_is_kept_and_duo_sequences_are_not(self):
        """A calibrated sequence inherits the shared task's filter, so the name decides."""
        tasks = [
            _prior(
                "light_vs_bias",
                "light_s233",
                "bkg_pp_light_s233_.seq",
                {"FILTER": "HaOiii"},
                session_id=233,
            ),
            _prior(
                "seqextract_haoiii",
                "seqextract_s237",
                "r_Ha_bkg_pp_light_s237_.seq",
                session_id=237,
            ),
            _prior(
                "light_vs_bias",
                "light_s237",
                "bkg_pp_light_s237_.seq",
                session_id=237,
            ),
        ]

        result = self._import("lights", tasks)

        assert result.image_rows is not None
        assert [row["path"] for row in result.image_rows] == ["bkg_pp_light_s233_.seq"]

    def test_no_broadband_sequence_rejects_the_stage(self):
        from starbash.exception import NotEnoughFilesError

        tasks = [_prior("seqextract_haoiii", "light_s237", "r_Ha_bkg_pp_light_s237_.seq")]
        with pytest.raises(NotEnoughFilesError):
            self._import("lights", tasks)

    def test_runs_after_the_stack_it_registers_to(self):
        ordered = sort_stages(
            [
                self.stage,
                {"name": "stack_dual_duo"},
                {"name": "stack_osc"},
                {"name": "crop", "inputs": [{"after": "stack_.*"}]},
                {"name": "background", "inputs": [{"after": "crop"}]},
            ]
        )
        names = [stage["name"] for stage in ordered]
        assert names.index("stack_dual_duo") < names.index("stack_broadband") < names.index("crop")
        assert names.index("crop") < names.index("background")


class TestStackOscDropsExtractedNights:
    """A duo night is already a plate. stack_osc must not stack it again."""

    def test_an_extracted_night_is_not_a_colour_input(self):
        from starbash.exception import NotEnoughFilesError

        stage = _load("osc/stack_osc.toml")["stages"][0]
        assert stage["inputs"][0]["after"] == "(?:seqextract_haoiii|light.*)"
        tasks = [
            _prior(
                "seqextract_haoiii",
                "seqextract_s237",
                "r_Ha_bkg_pp_light_s237_.seq",
                session_id=237,
            ),
            _prior("light_vs_bias", "light_s237", "bkg_pp_light_s237_.seq", session_id=237),
        ]
        processing = Processing.__new__(Processing)
        processing.stage = stage
        processing.processed_target = None
        processing.context = {"default_metadata": {}}
        processing._get_prior_tasks = lambda stage, input=None: tasks

        with pytest.raises(NotEnoughFilesError):
            processing._import_from_prior_stages(stage["inputs"][0])


class TestDownstreamGuards:
    @staticmethod
    def _filename_guards(stage: dict) -> list[dict]:
        return [
            requires
            for item in stage["inputs"]
            for requires in item.get("requires", [])
            if requires.get("kind") == "filename" and requires.get("value") == "stacked_bb"
        ]

    def test_background_adopts_the_star_plate(self):
        stage = _load("graxpert/background.toml")["stages"][0]
        assert self._filename_guards(stage) == []

    def test_broadband_palette_rejects_the_star_plate_by_name(self):
        stage = _load("palette/broadband.toml")["stages"][0]
        assert self._filename_guards(stage) == [
            {"kind": "filename", "value": "stacked_bb", "mode": "exclude"}
        ]


def _merge_context(broadband: FileInfo, stretch: float = 1000) -> dict:
    """The two inputs merge_stars expands: the starless file and the optional plate."""
    starless = Path("/tmp/hms_starless_SHO.fits")
    return {
        "input": {
            0: FileInfo(image_rows=[{"abspath": str(starless), "path": starless.name}]),
            "broadband": broadband,
        },
        "parameters": SimpleNamespace(stretch=stretch),
        "output": FileInfo(
            image_rows=[{"abspath": "/tmp/merged_SHO.fits", "path": "merged_SHO.fits"}]
        ),
    }


class TestMergeStarsBroadband:
    def test_optional_input_is_the_cropped_plate(self):
        stage = _load("post/merge_stars.toml")["stages"][0]
        broadband = next(item for item in stage["inputs"] if item.get("name") == "broadband")

        assert broadband["optional"] is True
        assert broadband["after"] == "(denoise|crop)"
        assert "multiplex" not in broadband
        assert broadband["requires"] == [{"kind": "filename", "value": "stacked_bb\\.fits$"}]
        assert "asinh -human {parameters.stretch}" in stage["script"]
        assert "1 - (1 - $starless$) * (1 - $stars$)" in stage["script"]

    def test_denoised_plate_wins_over_the_crop_it_consumed(self):
        stage = _load("post/merge_stars.toml")["stages"][0]
        broadband = next(item for item in stage["inputs"] if item.get("name") == "broadband")
        crop = "/tmp/crop_stacked_bb.fits"
        sharpened = "/tmp/bx_bk_crop_stacked_bb.fits"
        denoised = "/tmp/nx_bx_bk_crop_stacked_bb.fits"
        tasks = [
            _prior("crop", "crop_bb", "crop_stacked_bb.fits"),
            {
                "name": "blur_exterminator_bb",
                "meta": {
                    "stage": {"name": "blur_exterminator"},
                    "context": {
                        "session": {},
                        "default_metadata": {},
                        "input": {
                            0: FileInfo(
                                image_rows=[{"abspath": crop, "path": "crop_stacked_bb.fits"}]
                            )
                        },
                        "output": FileInfo(
                            base="/tmp",
                            image_rows=[
                                {"abspath": sharpened, "path": "bx_bk_crop_stacked_bb.fits"}
                            ],
                        ),
                    },
                },
            },
            {
                "name": "noise_exterminator_bb",
                "meta": {
                    "stage": {"name": "noise_exterminator"},
                    "context": {
                        "session": {},
                        "default_metadata": {},
                        "input": {
                            0: FileInfo(
                                image_rows=[
                                    {"abspath": sharpened, "path": "bx_bk_crop_stacked_bb.fits"}
                                ]
                            )
                        },
                        "output": FileInfo(
                            base="/tmp",
                            image_rows=[
                                {"abspath": denoised, "path": "nx_bx_bk_crop_stacked_bb.fits"}
                            ],
                        ),
                    },
                },
            },
        ]
        processing = Processing.__new__(Processing)
        processing.stage = stage
        processing.processed_target = None
        processing.context = {"default_metadata": {}}
        processing._built_tasks = []
        processing._get_prior_tasks = lambda stage, input=None: tasks

        imported = processing._import_from_prior_stages(broadband)

        assert imported.image_rows is not None
        assert [row["path"] for row in imported.image_rows] == ["nx_bx_bk_crop_stacked_bb.fits"]

    def test_a_sibling_reading_the_plate_does_not_replace_it(self):
        """stack_broadband reads stacked_Ha.fits; that must not drop the plate."""
        crop = next(item for item in _load("common/crop.toml")["stages"][0]["inputs"])
        plate = "/tmp/stacked_Ha.fits"
        broadband = "/tmp/stacked_bb.fits"
        tasks = [
            _prior("stack_dual_duo", "stack_dual_duo", "stacked_Ha.fits"),
            {
                "name": "stack_broadband",
                "meta": {
                    "stage": {"name": "stack_broadband"},
                    "context": {
                        "session": {},
                        "default_metadata": {},
                        "input": {
                            "ha": FileInfo(
                                image_rows=[{"abspath": plate, "path": "stacked_Ha.fits"}]
                            )
                        },
                        "output": FileInfo(
                            base="/tmp",
                            image_rows=[{"abspath": broadband, "path": "stacked_bb.fits"}],
                        ),
                    },
                },
            },
        ]
        processing = Processing.__new__(Processing)
        processing.stage = {"inputs": [crop]}
        processing.processed_target = None
        processing.context = {"default_metadata": {}}
        processing._built_tasks = tasks
        processing._get_prior_tasks = lambda stage, input=None: tasks

        imported = processing._import_from_prior_stages(crop)

        assert imported.image_rows is not None
        assert {row["path"] for row in imported.image_rows} == {
            "stacked_Ha.fits",
            "stacked_bb.fits",
        }

    def test_absent_plate_emits_todays_script(self):
        stage = _load("post/merge_stars.toml")["stages"][0]
        expanded = expand_context_unsafe(stage["script"], _merge_context(FileInfo(image_rows=[])))

        before_stretch = expanded.split("asinh -human", 1)[0]
        assert "load starmask" in before_stretch
        assert "pm " not in before_stretch
        assert "asinh -human 1000" in expanded

    def test_present_plate_is_projected_through_the_mask(self, tmp_path: Path):
        stage = _load("post/merge_stars.toml")["stages"][0]
        plate = tmp_path / "crop_stacked_bb.fits"
        expanded = expand_context_unsafe(
            stage["script"],
            _merge_context(FileInfo(image_rows=[{"abspath": str(plate), "path": plate.name}])),
        )

        masked = expanded.split("asinh -human", 1)[0]
        assert f'load "{plate}"' in masked
        assert "rgbcomp broadband broadband broadband" in masked
        assert 'pm "$broadband_rgb$ * $starmask$"' in masked
        assert (
            masked.index(f'load "{plate}"')
            < masked.index("rgbcomp")
            < masked.index("pm ")
            < masked.rindex("save starmask")
        )


class TestSirilLine:
    def test_empty_input_emits_nothing(self):
        assert siril_line(FileInfo(image_rows=[]), 'load "%s"') == ""
        assert siril_line(None, 'load "%s"') == ""

    def test_resolved_input_names_its_first_file(self, tmp_path: Path):
        plate = tmp_path / "crop_stacked_bb.fits"
        info = FileInfo(image_rows=[{"abspath": str(plate), "path": plate.name}])

        assert siril_line(info, 'load "%s"') == f'load "{plate}"'


def test_stack_broadband_fails_before_siril_without_one_sequence(monkeypatch, tmp_path: Path):
    plate = tmp_path / "stacked_Ha.fits"
    run = MagicMock()
    monkeypatch.setattr(osc.siril, "run", run)
    monkeypatch.setattr(
        osc,
        "context",
        {
            "input": {
                "ha": FileInfo(image_rows=[{"abspath": str(plate), "path": plate.name}]),
                "lights": FileInfo(image_rows=[]),
            },
            "output": SimpleNamespace(base=str(tmp_path)),
            "process_dir": str(tmp_path),
        },
    )

    with pytest.raises(Exception, match="exactly one sequence"):
        osc.stack_broadband()

    run.assert_not_called()


#: Real-Siril tests are skipped where Siril is not installed (CI installs it).
SIRIL_AVAILABLE = tools["siril"].is_available


def _write_frame(path: Path, width: int, height: int, shift: tuple[int, int]) -> None:
    """A frame with a field of stars, shifted by whole pixels.

    One star is not enough for Siril's star alignment (it wants several pairs).
    The field is the same pattern in every frame, so the brightest star is the
    one the test looks for after registration.
    """
    pixels = np.full((192, 256), 0.02, dtype=np.float32)
    dy, dx = shift
    radius = 4
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    profile = np.exp(-(yy**2 + xx**2) / 4.0).astype(np.float32)
    centres = [
        (28, 24),
        (30, 92),
        (36, 150),
        (34, 214),
        (78, 48),
        (84, 118),
        (76, 188),
        (126, 30),
        (132, 96),
        (124, 162),
        (130, 220),
        (168, 62),
        (164, 138),
        (170, 198),
    ]
    for index, (y, x) in enumerate(centres):
        brightness = 0.6 + 0.02 * index
        y0, x0 = y + dy, x + dx
        pixels[y0 - radius : y0 + radius + 1, x0 - radius : x0 + radius + 1] = np.maximum(
            pixels[y0 - radius : y0 + radius + 1, x0 - radius : x0 + radius + 1],
            profile * brightness,
        )
    fits.PrimaryHDU(pixels).writeto(path)


@pytest.mark.skipif(not SIRIL_AVAILABLE, reason="Siril is not installed")
class TestBroadbandRegistrationWithSiril:
    """The plate is a member of the sequence, so registration lands on its grid."""

    def test_shifted_star_lands_on_the_plate(self, monkeypatch, tmp_path: Path):
        work = tmp_path / "work"
        lights = work / "bb"
        lights.mkdir(parents=True)
        plate = tmp_path / "stacked_Ha.fit"
        _write_frame(plate, 0, 0, (0, 0))
        # The first light is not a copy of the plate. If registration ignored the
        # pin and used that light, the stacked star would land 5 columns off.
        for index, shift in enumerate((5, -5, 8), start=1):
            _write_frame(lights / f"light_{index:05d}.fit", 0, 0, (0, shift))
        output = tmp_path / "stacked_bb.fit"
        monkeypatch.setattr(
            osc,
            "context",
            {"process_dir": str(work), "output": SimpleNamespace(base=str(tmp_path))},
        )

        register, apply, stack = osc.broadband_stack_commands(
            "bb", 3, plate, lights, output, drizzle="", filtering=""
        )
        # These synthetic frames are a flat sky plus stars, so the normalization
        # the real stage uses has no noise to measure and aborts. The test is
        # about the registration, not the rejection, so the stack is additive.
        stack = stack.replace("-norm=addscale -output_norm", "-nonorm")
        osc.siril.run(register, context={"input_files": []}, cwd=str(lights))
        osc.write_reference_identity(lights / "bb_.seq")
        osc.siril.run(apply, context={"input_files": []}, cwd=str(lights))
        plate_index = osc.applied_member_index(lights / "r_bb_.seq", 4)
        osc.siril.run(
            f"unselect r_bb {plate_index} {plate_index}\n{stack}",
            context={"input_files": []},
            cwd=str(lights),
        )

        assert output.exists()
        assert read_dimensions(output) == (256, 192)
        # framing=cog recentres the canvas, so the plate itself moves. That is
        # the same framing the narrowband plates used, which is what makes the
        # two agree. The lights have to land on the exported plate, not on the
        # coordinates they were planted at.
        plate_out = np.asarray(fits.getdata(next(lights.glob("r_bb_00004.fit*"))))
        plate_peak = np.unravel_index(int(np.argmax(plate_out)), plate_out.shape)
        light_out = np.asarray(fits.getdata(next(lights.glob("r_bb_00001.fit*"))))
        light_peak = np.unravel_index(int(np.argmax(light_out)), light_out.shape)
        assert light_peak == plate_peak
        # mirrorx flips the stack the way it flips the other plates.
        stacked = np.asarray(fits.getdata(output))
        stacked_peak = np.unravel_index(int(np.argmax(stacked)), stacked.shape)
        assert stacked_peak[1] == plate_peak[1]
        assert stacked_peak[0] == stacked.shape[0] - 1 - plate_peak[0]
