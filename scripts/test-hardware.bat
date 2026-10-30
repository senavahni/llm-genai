@echo off
rem Test hardware di mesin target (manual sebelum rilis): model OpenVINO nyata di GPU/NPU.
rem   - tests\hardware\test_llm.py, test_sd_npu.py : backend langsung (runtime boleh MATI agar
rem     memori GPU/NPU tidak dipakai dua proses)
rem   - tests\hardware\test_gateway_e2e.py          : lewat gateway + runtime yang BERJALAN,
rem     butuh LGW_TEST_KEY (key client dengan akses local/*); LGW_SWAP_N (default 100)
rem Contoh: scripts\test-hardware.bat tests\hardware\test_gateway_e2e.py
call "%~dp0env.bat"
if "%~1"=="" (
  "%PY%" -m pytest --hardware -s -v tests\hardware
) else (
  "%PY%" -m pytest --hardware -s -v %*
)
