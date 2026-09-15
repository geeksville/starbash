ci fails on mac os with

2026-09-15T19:58:20.3903890Z   grax-denoise: grax-denoise_ic434_i0
2026-09-15T19:58:20.3905180Z   Running: graxpert -cmd denoising -output /private/var/folders/36/tjdph2t965j8snz9_vkdnw0r0000gn/T/pytest-of-runner/pytest-0/workflow0/documents/repos/processed/ic434/denoise_dco_bk_crop_stacked.fits /private/var/folders/36/tjdph2t965j8snz9_vkdnw0r0000gn/T/pytest-of-runner/pytest-0/workflow0/documents/repos/processed/ic434/dco_bk_crop_stacked.fits
2026-09-15T19:58:20.3905410Z   Starting GraXpert CLI, Denoising, version: 3.2.0a2 release: fix gui launch
2026-09-15T19:58:20.3905540Z   Using stored denoise strength value 0.5.
2026-09-15T19:58:20.3905650Z   Using stored batch size value 4.
2026-09-15T19:58:20.3905770Z   Using stored gpu acceleration setting True.
2026-09-15T19:58:20.3906090Z   Using AI version 3.0.2. You can overwrite this by providing the argument '-ai_version'
2026-09-15T19:58:20.3906240Z   AI version 3.0.2 not found locally, downloading...
2026-09-15T19:58:20.3906340Z   download successful
2026-09-15T19:58:20.3906500Z   Excecuting denoising with the following parameters:
2026-09-15T19:58:20.3906840Z   AI model path - /Users/runner/Library/Application Support/GraXpert/denoise-ai-models/3.0.2/model.onnx
2026-09-15T19:58:20.3906950Z   denoise strength - 0.5
2026-09-15T19:58:20.3907020Z   Starting denoising
2026-09-15T19:58:20.3907430Z   Available inference providers : [('CoreMLExecutionProvider', {'flags': 'COREML_FLAG_CREATE_MLPROGRAM'}), 'CPUExecutionProvider']
2026-09-15T19:58:20.3907550Z   Auto-processing: interrupted
2026-09-15T19:58:20.3907640Z   Auto-processing
2026-09-15T19:58:20.3908440Z   ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
2026-09-15T19:58:20.3908960Z   ┃ Target                                                     ┃ Stage             ┃ Task                    ┃ Status  ┃ Outputs                                                                     ┃
2026-09-15T19:58:20.3909520Z   ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
2026-09-15T19:58:20.3910190Z   │ Master bias_gain0 · 2025-09-10 · zwoasi2600mcduo           │ master_bias       │ master_bias_s43         │ Success │ zwoasi2600mcduo/2025-09-10_03-31-44/bias/master_bias_gain0.fit              │
2026-09-15T19:58:20.3911020Z   │ Master flat_HaOiii_gain100 · 2025-09-23 · zwoasi2600mcduo  │ master_flat       │ master_flat_m20_s39     │ Success │ ascarv80mmextender/2025-09-23_03-36-20/flat/master_flat_HaOiii_gain100.fit  │
2026-09-15T19:58:20.3911760Z   │ Master flat_SiiOiii_gain100 · 2025-09-23 · zwoasi2600mcduo │ master_flat       │ master_flat_m20_s40     │ Success │ ascarv80mmextender/2025-09-23_03-37-52/flat/master_flat_SiiOiii_gain100.fit │
2026-09-15T19:58:20.3912340Z   │ ic434                                                      │ light_no_darks    │ light_no_darks_ic434_s5 │ Success │ bkg_pp_light_s5_.seq                                                        │
2026-09-15T19:58:20.3912840Z   │ ic434                                                      │ stack_osc         │ stack_osc_ic434         │ Success │ stacked.fits                                                                │
2026-09-15T19:58:20.3913400Z   │ ic434                                                      │ report_stack_osc  │ report_stack_osc_ic434  │ Success │ stacked.fits                                                                │
2026-09-15T19:58:20.3914320Z   │ ic434                                                      │ palette_broadband │                         │ Pending │                                                                             │
2026-09-15T19:58:20.3914930Z   │ ic434                                                      │ crop              │ crop_ic434_i0           │ Success │ crop_stacked.fits                                                           │
2026-09-15T19:58:20.3915410Z   │ ic434                                                      │ veralux           │                         │ Pending │                                                                             │
2026-09-15T19:58:20.3915930Z   │ ic434                                                      │ background        │ background_ic434_i0     │ Success │ bk_crop_stacked.fits                                                        │
2026-09-15T19:58:20.3916510Z   │ ic434                                                      │ deconv-obj        │ deconv-obj_ic434_i0     │ Success │ dco_bk_crop_stacked.fits                                                    │
2026-09-15T19:58:20.3917130Z   │ ic434                                                      │ grax-denoise      │ grax-denoise_ic434_i0   │ Running │ denoise_dco_bk_crop_stacked.fits                                            │
2026-09-15T19:58:20.3917580Z   │ ic434                                                      │ thumbnail         │                         │ Pending │                                                                             │
2026-09-15T19:58:20.3918140Z   └────────────────────────────────────────────────────────────┴───────────────────┴─────────────────────────┴─────────┴─────────────────────────────────────────────────────────────────────────────┘
2026-09-15T19:58:20.3918240Z   
2026-09-15T19:58:20.3918330Z assert 1 == 0
2026-09-15T19:58:20.3918620Z  +  where 1 = <Result RuntimeError('doit processing failed with exit code 3')>.exit_code
2026-09-15T19:58:20.3918800Z ===== 1 failed, 12 passed, 1267 deselected, 1 warning in 652.04s (0:10:52) =====
2026-09-15T19:58:21.0437670Z E5RT encountered an STL exception. msg = Input: gen_input_image has unbounded dimension which is not supported. Please consult MIL Framework or milPython on adding a bound for this dimension..E5RT encountered an STL exception. msg = Input: StatefulPartitionedCall_model_sequential_7_batch_normalization_6_FusedBatchNormV3__62_0 has unbounded dimension which is not supported. Please consult MIL Framework or milPython on adding a bound for this dimension..E5RT encountered an STL exception. msg = Input: StatefulPartitionedCall_model_sequential_1_leaky_re_lu_1_LeakyRelu_0 has unbounded dimension which is not supported. Please consult MIL Framework or milPython on adding a bound for this dimension..E5RT encountered an STL exception. msg = Input: gen_input_image has unbounded dimension which is not supported. Please consult MIL Framework or milPython on adding a bound for this dimension..E5RT encountered an STL exception. msg = Input: _down_layers_1_norm1_cond_Slice_output_0 has unbounded dimension which is not supported. Please consult MIL Framework or milPython on adding a bound for this dimension..E5RT encountered an STL exception. msg = Failed to PropagateInputTensorShapes: Invalid tensor rank 0 inferred from: ios18.squeeze, expecting 1..E5RT encountered an STL exception. msg = Failed to PropagateInputTensorShapes: Invalid tensor rank 0 inferred from: ios18.squeeze, expecting 1..E5RT encountered an STL exception. msg = Input: _encoders_0_encoders_0_0_norm1_Div_output_0 has unbounded dimension which is not supported. Please consult MIL Framework or milPython on adding a bound for this dimension..E5RT encountered an STL exception. msg = Failed to PropagateInputTensorShapes: std::invalid_argument during type inference for ios18.conv: output size is too small..E5RT encountered an STL exception. msg = Failed to PropagateInputTensorShapes: std::invalid_argument during type inference for ios18.mul: Shapes are not compatible for broadcasting..
2026-09-15T19:58:21.0561750Z ##[error]Process completed with exit code 1.