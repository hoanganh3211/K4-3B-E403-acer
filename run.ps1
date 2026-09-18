param([ValidateSet('api','ui','test')][string]$Service = 'ui')
$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonExecutable = Join-Path $projectDirectory 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Chưa có venv. Chạy: py -m venv venv; .\venv\Scripts\python.exe -m pip install -r requirements.txt'
}
Push-Location -LiteralPath $projectDirectory
try {
    switch ($Service) {
        'api' { & $pythonExecutable -m uvicorn api_server:app --host 127.0.0.1 --port 8000 }
        'ui' { & $pythonExecutable -m streamlit run app_ui.py --server.address 127.0.0.1 --server.port 8501 }
        'test' { & $pythonExecutable -m unittest discover -s tests -p 'test_*.py' -v }
    }
} finally {
    Pop-Location
}
