# dwarf3 fits info

Dwarf3 fits headers seem to be much more sparse than ASI or NINA.  But I think if the filenames are stable I can pretty easily populate the missing 'fits' info from the filepath.

Some rules:

* CALI_FRAME are the prefered sources of bias,dark,flat frames.  Look for that rooot directory name in particular.  These files are set at mfg time and never change, therefore no need to care about file dates.
* DWARF_DARK might exist and if it exist it contains only dark frames.  These files do contain usefule DATE-OBS.
* For imaging sessions with light frames the raws directory (the only directory we care about) will contain a shotsInfo.json file.

FIXME - which cam (0 or 1) is "TELE"?  What is the name of the other camera?

Therefore, when importing raws:

* If key metadata is missing from the file call try_dwarf_import():
  * If within a CALI_FRAME tree parse the filepath to get exposure, gain, temperature, binning.  Add to metadata as bias/dark/flat.
  * If within a DWARF_DARK tree parse all the same things, but also parse the date.  Add to metadata as dark.
  * If the directory with the image contains a shotsInfo.json file, import using the filename parsing + json info.  Add to metadata as light.
* If after all these fixups are applied key metadata is still missing (mainly IMAGETYP and DATE-OBS), drop the image and spit out a warning.

## Credits and thanks

These files were kindly donated by [Bitgistics](mailto:zonezero@gmail.com) to facilitate supporting Dwarf3 telescopes in starbash.

## Full directory tree

```
├── CALI_FRAME
│   ├── bias
│   │   ├── cam_0
│   │   │   └── bias_gain_2_bin_1.fits
│   │   └── cam_1
│   │       └── bias_gain_2_bin_1.fits
│   ├── dark
│   │   ├── cam_0
│   │   │   ├── dark_exp_15.000000_gain_130_bin_1_16C_stack_10.fits
│   │   │   ├── dark_exp_15.000000_gain_60_bin_1_28C_stack_3.fits
│   │   │   ├── dark_exp_30.000000_gain_40_bin_1_15C_stack_7.fits
│   │   │   ├── dark_exp_30.000000_gain_40_bin_1_16C_stack_3.fits
│   │   │   ├── dark_exp_30.000000_gain_60_bin_1_29C_stack_1.fits
│   │   │   ├── dark_exp_60.000000_gain_60_bin_1_20C_stack_8.fits
│   │   │   ├── dark_exp_60.000000_gain_60_bin_1_21C_stack_7.fits
│   │   │   ├── dark_exp_60.000000_gain_60_bin_1_22C_stack_5.fits
│   │   │   └── dark_exp_60.000000_gain_60_bin_1_29C_stack_1.fits
│   │   └── cam_1
│   │       ├── dark_exp_15.000000_gain_60_bin_1_29C_stack_3.fits
│   │       ├── dark_exp_30.000000_gain_60_bin_1_29C_stack_1.fits
│   │       └── dark_exp_60.000000_gain_60_bin_1_29C_stack_1.fits
│   └── flat
│       ├── cam_0
│       │   ├── flat_gain_2_bin_1_ir_0.fits
│       │   ├── flat_gain_2_bin_1_ir_1.fits
│       │   └── flat_gain_2_bin_1_ir_2.fits
│       └── cam_1
│           └── flat_gain_2_bin_1.fits
├── DWARF_DARK
│   ├── tele_exp_15_gain_130_bin_1_2025-10-31-05-42-52-480
│   │   ├── raw_15s_130_0000_20251031-054306711_16C.fits
│   │   ├── raw_15s_130_0001_20251031-054321700_16C.fits
│   │   ├── raw_15s_130_0002_20251031-054336706_16C.fits
│   │   ├── raw_15s_130_0003_20251031-054351699_16C.fits
│   │   ├── raw_15s_130_0004_20251031-054406700_16C.fits
│   │   ├── raw_15s_130_0005_20251031-054421701_16C.fits
│   │   ├── raw_15s_130_0006_20251031-054436708_16C.fits
│   │   ├── raw_15s_130_0007_20251031-054451711_16C.fits
│   │   ├── raw_15s_130_0008_20251031-054506708_16C.fits
│   │   └── raw_15s_130_0009_20251031-054521704_16C.fits
│   ├── tele_exp_30_gain_40_bin_1_2025-10-30-23-55-59-652
│   │   ├── raw_30s_40_0000_20251030-235628894_16C.fits
│   │   ├── raw_30s_40_0001_20251030-235658868_16C.fits
│   │   ├── raw_30s_40_0002_20251030-235728846_16C.fits
│   │   ├── raw_30s_40_0003_20251030-235758826_15C.fits
│   │   ├── raw_30s_40_0004_20251030-235828817_15C.fits
│   │   ├── raw_30s_40_0005_20251030-235858795_15C.fits
│   │   ├── raw_30s_40_0006_20251030-235928777_15C.fits
│   │   ├── raw_30s_40_0007_20251030-235958758_15C.fits
│   │   ├── raw_30s_40_0008_20251031-000028737_15C.fits
│   │   └── raw_30s_40_0009_20251031-000058715_15C.fits
│   ├── tele_exp_60_gain_60_bin_1_2025-10-18-02-42-14-084
│   │   ├── raw_60s_60_0000_20251018-024313362_22C.fits
│   │   ├── raw_60s_60_0001_20251018-024413338_22C.fits
│   │   ├── raw_60s_60_0002_20251018-024513324_22C.fits
│   │   ├── raw_60s_60_0003_20251018-024613303_22C.fits
│   │   ├── raw_60s_60_0004_20251018-024713280_22C.fits
│   │   ├── raw_60s_60_0005_20251018-024813257_21C.fits
│   │   ├── raw_60s_60_0006_20251018-024913226_21C.fits
│   │   ├── raw_60s_60_0007_20251018-025013202_21C.fits
│   │   ├── raw_60s_60_0008_20251018-025113179_21C.fits
│   │   └── raw_60s_60_0009_20251018-025213155_21C.fits
│   └── tele_exp_60_gain_60_bin_1_2025-10-20-03-20-10-952
│       ├── raw_60s_60_0000_20251020-032110230_21C.fits
│       ├── raw_60s_60_0001_20251020-032210208_21C.fits
│       ├── raw_60s_60_0002_20251020-032310186_20C.fits
│       ├── raw_60s_60_0003_20251020-032410162_20C.fits
│       ├── raw_60s_60_0004_20251020-032510151_20C.fits
│       ├── raw_60s_60_0005_20251020-032610116_20C.fits
│       ├── raw_60s_60_0006_20251020-032710103_20C.fits
│       ├── raw_60s_60_0007_20251020-032810082_20C.fits
│       ├── raw_60s_60_0008_20251020-032910048_20C.fits
│       └── raw_60s_60_0009_20251020-033010025_20C.fits
├── IC 434 Horsehead Nebula
│   ├── 5f5f2445a2e4262b38479f47579ca4d5.fits
│   ├── 8e0ff8e1ca99eaa25792762684aa582a_20251018060102363.jpg
│   ├── be462964bac357582c3f44e5426cd640_20251018060048334.png
│   ├── DWARF_20251018055913630.jpeg
│   └── DWARF_RAW_TELE_IC 434_EXP_60_GAIN_60_2025-10-18-04-51-22-420
│       ├── 5f5f2445a2e4262b38479f47579ca4d5.fits
│       ├── failed_IC 434_60s60_Astro_20251018-045526506_16C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-051725998_15C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-053125666_14C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-053325620_14C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-053625552_13C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-053725538_13C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-054325391_13C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-054725310_13C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-054825279_13C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-054925265_13C.fits
│       ├── failed_IC 434_60s60_Astro_20251018-055025242_13C.fits
│       ├── IC 434_60s60_Astro_20251018-045226559_17C.fits
│       ├── IC 434_60s60_Astro_20251018-045326538_17C.fits
│       ├── IC 434_60s60_Astro_20251018-045426515_17C.fits
│       ├── IC 434_60s60_Astro_20251018-045626468_16C.fits
│       ├── IC 434_60s60_Astro_20251018-045726457_16C.fits
│       ├── IC 434_60s60_Astro_20251018-045826426_16C.fits
│       ├── IC 434_60s60_Astro_20251018-045926401_16C.fits
│       ├── IC 434_60s60_Astro_20251018-050026388_16C.fits
│       ├── IC 434_60s60_Astro_20251018-050126355_16C.fits
│       ├── IC 434_60s60_Astro_20251018-050326320_15C.fits
│       ├── IC 434_60s60_Astro_20251018-050426285_15C.fits
│       ├── IC 434_60s60_Astro_20251018-050526262_15C.fits
│       ├── IC 434_60s60_Astro_20251018-050626254_15C.fits
│       ├── IC 434_60s60_Astro_20251018-050726228_15C.fits
│       ├── IC 434_60s60_Astro_20251018-050826194_15C.fits
│       ├── IC 434_60s60_Astro_20251018-050926170_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051026148_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051126125_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051226102_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051426067_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051526033_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051626020_15C.fits
│       ├── IC 434_60s60_Astro_20251018-051825974_14C.fits
│       ├── IC 434_60s60_Astro_20251018-051925953_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052025930_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052125906_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052225884_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052325861_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052525815_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052625781_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052725770_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052825735_14C.fits
│       ├── IC 434_60s60_Astro_20251018-052925724_14C.fits
│       ├── IC 434_60s60_Astro_20251018-053025700_14C.fits
│       ├── IC 434_60s60_Astro_20251018-053225643_14C.fits
│       ├── IC 434_60s60_Astro_20251018-053425598_13C.fits
│       ├── IC 434_60s60_Astro_20251018-053825505_13C.fits
│       ├── IC 434_60s60_Astro_20251018-053925482_13C.fits
│       ├── IC 434_60s60_Astro_20251018-054025459_13C.fits
│       ├── IC 434_60s60_Astro_20251018-054125448_13C.fits
│       ├── IC 434_60s60_Astro_20251018-054225416_13C.fits
│       ├── IC 434_60s60_Astro_20251018-054425378_13C.fits
│       ├── IC 434_60s60_Astro_20251018-054525345_13C.fits
│       ├── img_reference.png
│       ├── img_stacked_all.tif
│       ├── img_stacked_counter.png
│       ├── shotsInfo.json
│       ├── stacked-16_IC 434_60s60_Astro_20251018-045127226.fits
│       ├── stacked-16_IC 434_60s60_Astro_20251018-045127226.png
│       ├── stacked.jpg
│       ├── stacked_thumbnail.jpg
│       └── Thumbnail
│           ├── failed_IC 434_60s60_Astro_20251018-045526506_16C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-051725998_15C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-053125666_14C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-053325620_14C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-053625552_13C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-053725538_13C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-054325391_13C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-054725310_13C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-054825279_13C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-054925265_13C.jpg
│           ├── failed_IC 434_60s60_Astro_20251018-055025242_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-045326538_17C.jpg
│           ├── IC 434_60s60_Astro_20251018-045426515_17C.jpg
│           ├── IC 434_60s60_Astro_20251018-045626468_16C.jpg
│           ├── IC 434_60s60_Astro_20251018-045726457_16C.jpg
│           ├── IC 434_60s60_Astro_20251018-045826426_16C.jpg
│           ├── IC 434_60s60_Astro_20251018-045926401_16C.jpg
│           ├── IC 434_60s60_Astro_20251018-050026388_16C.jpg
│           ├── IC 434_60s60_Astro_20251018-050126355_16C.jpg
│           ├── IC 434_60s60_Astro_20251018-050326320_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-050426285_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-050526262_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-050626254_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-050726228_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-050826194_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-050926170_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051026148_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051126125_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051226102_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051426067_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051526033_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051626020_15C.jpg
│           ├── IC 434_60s60_Astro_20251018-051825974_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-051925953_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052025930_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052125906_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052225884_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052325861_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052525815_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052625781_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052725770_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052825735_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-052925724_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-053025700_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-053225643_14C.jpg
│           ├── IC 434_60s60_Astro_20251018-053425598_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-053825505_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-053925482_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-054025459_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-054125448_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-054225416_13C.jpg
│           ├── IC 434_60s60_Astro_20251018-054425378_13C.jpg
│           └── IC 434_60s60_Astro_20251018-054525345_13C.jpg
└── README.md

19 directories, 179 files
```