# dwarf3 fits info

Dwarf3 fits headers seem to be much more sparse than ASI or NINA.  But I think if the filenames are stable I can pretty easily populate the missing 'fits' info from the filepath.

Questions for Randall (ps: thanks again!):

* The directory names you sent me, how much of that path was 'picked by you' vs. 'the standard path and filename Dwarf3 auto-populates'?  (I'm hoping that much of that pathname was standard so that I can go 'oh fits headers say this came from Dwarf3, populate extra stuff from the filename)
* For instance, for bias frames "somedir/CALI_FRAME/bias/cam_0/bias_gain_2_bin_1.fits", what parts of the filename did Dwarf pick?  Did they pick CALI_FRAME as the name or did you?
* Same question wrt a typical dark frame "somedir/DWARF_DARK/tele_exp_60_gain_60_bin_1_2025-10-20-03-20-10-952/raw_60s_60_0002_20251020-032310186_20C.fits"?
* Same question wrt a typical light frame "somedir/IC 434 Horsehead Nebula/DWARF_RAW_TELE_IC 434_EXP_60_GAIN_60_2025-10-18-04-51-22-420/IC 434_60s60_Astro_20251018-045926401_16C.fits"?
* There are two 'darks' directories (with slightly different FITS contents).  Do you know the relationship between "somedir/CALI_FRAME/dark/cam_0" and "somedir/DWARF_DARK"?

