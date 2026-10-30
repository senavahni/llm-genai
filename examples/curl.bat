@echo off
rem Contoh HTTP mentah dengan curl.exe bawaan Windows (debug header & SSE). Butuh LGW_API_KEY.
if "%LGW_BASE_URL%"=="" set "LGW_BASE_URL=http://127.0.0.1:8000/v1"

echo === daftar model yang boleh dipakai key ini
curl -s "%LGW_BASE_URL%/models" -H "Authorization: Bearer %LGW_API_KEY%"
echo.

echo === chat non-stream (-i: tampilkan header X-Gateway-* dan X-Request-ID)
curl -s -i "%LGW_BASE_URL%/chat/completions" -H "Authorization: Bearer %LGW_API_KEY%" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"Halo\"}],\"max_tokens\":20}"
echo.

echo === stream SSE (-N: tanpa buffer, tiap baris data: tampil saat tiba)
curl -s -N "%LGW_BASE_URL%/chat/completions" -H "Authorization: Bearer %LGW_API_KEY%" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"fast\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Hitung 1 sampai 3\"}],\"max_tokens\":20}"
echo.

echo === FIM
curl -s "%LGW_BASE_URL%/completions" -H "Authorization: Bearer %LGW_API_KEY%" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"autocomplete\",\"prompt\":\"def add(a, b):\\n\",\"suffix\":\"\\n\",\"max_tokens\":24,\"temperature\":0}"
echo.
