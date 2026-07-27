# backup_muslimoon.ps1 - бэкап журналов и исходников Muslimoon
# Копирует: все журналы (.md) + bot.py + miniapp\index.html
#   1) свежие копии -> Muslimoon_BACKUP\
#   2) дневной снимок -> Muslimoon_BACKUP\snapshots\<дата>\  (история не теряется)
#   3) Muslimoon_RECOVERY.zip  (для восстановления)
#   -Monthly: дополнительно отдельный месячный зип Muslimoon_MONTHLY_<ГГГГ-ММ>.zip (хранится, 11-го числа)
param([switch]$Monthly)
$ErrorActionPreference = 'Stop'
$proj  = '%USERPROFILE%\Documents\MUSLIMOON BOT claud'
$bk    = '%USERPROFILE%\Documents\Google drive s\Muslimoon_BACKUP'
$zip   = Join-Path $bk 'Muslimoon_RECOVERY.zip'
$stamp = Get-Date -Format 'yyyy-MM-dd'
$now   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

New-Item -ItemType Directory -Force -Path $bk | Out-Null

# ключевые файлы (имена берём из ФС, без литералов-кириллицы в коде)
$items = @()
$items += Get-ChildItem -Path $proj -Filter *.md -File
$bp = Join-Path $proj 'bot.py';             if (Test-Path $bp) { $items += Get-Item $bp }
$ih = Join-Path $proj 'miniapp\index.html'; if (Test-Path $ih) { $items += Get-Item $ih }

# ⭐ ТИР-1 — НЕВОСПОЛНИМЫЙ чистовик (05.07.2026: владелец справедливо не доверял «лёгкому» бэкапу —
#   проверка показала, что проект 34-36ГБ, а бэкап был ~4-8МБ. Правило "гигантские JSON не бэкапим,
#   пересобираются формулами" ВЕРНО для баз, реально пересобираемых из первоисточников (Мактаба, издания).
#   НО чистовик Мухэймина — это МНОГОМЕСЯЧНЫЙ труд выверки книги Муршида против первоисточников,
#   формула его НЕ пересоберёт (нет "рецепта", воссоздать = переделать всю ручную+ИИ работу заново).
#   Оба файла умещаются в лимит Telegram (50МБ) — бэкапим их ВСЕГДА, невзирая на размер.
$muhayminNames = @('1_Muhaymin_al.json','muhaimin_full.json')
foreach ($n in $muhayminNames) { $p = Join-Path $proj $n; if (Test-Path $p) { $items += Get-Item $p } }

# ФОРМУЛЫ (закон владельца 01.07.2026: «базы большие не надо — если надо формулы собирай»):
#   все .py/.ps1-скрипты сборки/восстановления баз (корень + Ollama/1_perevod_murshida) — это рецепты,
#   по которым любую гигантскую базу можно пересобрать. Сами базы (большие .json/.db) НЕ бэкапим.
$formulas = @()
$formulas += Get-ChildItem -Path $proj -Filter *.py  -File
$formulas += Get-ChildItem -Path $proj -Filter *.ps1 -File
$ollama = Join-Path $proj 'Ollama\1_perevod_murshida'
if (Test-Path $ollama) { $formulas += Get-ChildItem -Path $ollama -Filter *.py -File }

# КОНФИГ/СОСТОЯНИЕ (мелкие, не базы): настройки запуска, метки прочитанных заявок/ошибок, очередь анонсов
$cfgNames = @('sources_40.json','update_notes_queue.json','update_note.txt','release_notes.txt',
              '_last_seen_request_id.txt','_last_seen_error_seq.txt','ver.txt','.claude\launch.json',
              'miniapp\requests_status.json','miniapp\requests_asof.txt')
$config = @()
foreach ($n in $cfgNames) { $p = Join-Path $proj $n; if (Test-Path $p) { $config += Get-Item $p } }

# 1) свежие копии в корень бэкапа (core — плоско, как было; restore не меняется)
foreach ($it in $items) { Copy-Item $it.FullName (Join-Path $bk $it.Name) -Force }

# 1.1) формулы -> Muslimoon_BACKUP\formulas\ (зеркало, только скрипты — .db/большие .json исключены самим фильтром)
$fdst = Join-Path $bk 'formulas'
New-Item -ItemType Directory -Force -Path $fdst | Out-Null
foreach ($it in $formulas) { Copy-Item $it.FullName (Join-Path $fdst $it.Name) -Force }

# 1.2) конфиг/состояние -> Muslimoon_BACKUP\config\
$cdst = Join-Path $bk 'config'
New-Item -ItemType Directory -Force -Path $cdst | Out-Null
foreach ($it in $config) { Copy-Item $it.FullName (Join-Path $cdst $it.Name) -Force }

# 1.5) папка АССИСТЕНТА (код + журнал + knowledge), БЕЗ гигантских индексов/книг (С45)
$asrc = Join-Path $proj 'Ассистент_Муслимун'
if (Test-Path $asrc) {
  $adst = Join-Path $bk 'Ассистент_Муслимун'
  # зеркало только лёгких файлов: .py .md .json .txt (db/книги не трогаем)
  robocopy $asrc $adst *.py *.md *.json *.txt /MIR /XF *.db /NJH /NJS /NDL /NC /NS /NP | Out-Null
}

# 1.6) НАКОПИТЕЛИ ИИ-знаний из git-ветки data (05.07.2026: найдена дыра — translations.json и
#   похожие жили ТОЛЬКО в ветке data, не бэкапились никак, хотя это платный невосполнимый труд ИИ,
#   не "гигантская пересобираемая формулой база". Порог 2МБ отсекает реально гигантские базы
#   (ahmad_3a/3b, hadiths_complete, muhaymin_index, reverse_index) — их продолжаем НЕ бэкапить,
#   пересобираются формулами. Всё МЕЛЬШЕ порога -> реальный накопитель, бэкапим.
$ndst = Join-Path $bk 'data_nakopiteli'
New-Item -ItemType Directory -Force -Path $ndst | Out-Null
try {
    $listing = Invoke-RestMethod -Uri 'https://api.github.com/repos/germanyalfurqan-eng/hadith-bot/contents/?ref=data' -TimeoutSec 30
    foreach ($it in $listing) {
        if ($it.type -eq 'file' -and $it.size -lt 2097152 -and ($it.name -match '\.(json|txt)$')) {
            try {
                Invoke-WebRequest -Uri "https://raw.githubusercontent.com/germanyalfurqan-eng/hadith-bot/data/$($it.name)" `
                    -OutFile (Join-Path $ndst $it.name) -TimeoutSec 30
            } catch { Write-Warning "data_nakopiteli: не скачал $($it.name): $_" }
        }
    }
} catch { Write-Warning "data_nakopiteli: не удалось получить листинг ветки data: $_" }

# 2) дневной снимок журналов (по дате -> история сохраняется)
$snap = Join-Path $bk ('snapshots\' + $stamp)
New-Item -ItemType Directory -Force -Path $snap | Out-Null
foreach ($it in (Get-ChildItem -Path $proj -Filter *.md -File)) { Copy-Item $it.FullName (Join-Path $snap $it.Name) -Force }

# 3) recovery zip (core — плоско в корне зипа; формулы и конфиг — в подпапках formulas\ / config\)
$tmp = Join-Path $env:TEMP ('musl_rec_' + [System.Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
foreach ($it in $items) { Copy-Item $it.FullName (Join-Path $tmp $it.Name) -Force }
$tf = Join-Path $tmp 'formulas'; New-Item -ItemType Directory -Force -Path $tf | Out-Null
foreach ($it in $formulas) { Copy-Item $it.FullName (Join-Path $tf $it.Name) -Force }
$tc = Join-Path $tmp 'config';   New-Item -ItemType Directory -Force -Path $tc | Out-Null
foreach ($it in $config) { Copy-Item $it.FullName (Join-Path $tc $it.Name) -Force }
$tn = Join-Path $tmp 'data_nakopiteli'; New-Item -ItemType Directory -Force -Path $tn | Out-Null
if (Test-Path $ndst) { foreach ($it in (Get-ChildItem -Path $ndst -File)) { Copy-Item $it.FullName (Join-Path $tn $it.Name) -Force } }
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $tmp '*') -DestinationPath $zip -Force
Remove-Item $tmp -Recurse -Force

# 3.5) УКАЗ-4 (#210): ВЕРСИОННЫЙ бэкап — при КАЖДОЙ новой версии (APPVER) отдельный зип с датой+описанием,
#      чтобы можно было откатиться к ЛЮБОЙ версии. Один снимок на версию (первый раз, как увидели vNNN).
try {
  $ver = $null
  if (Test-Path $ih) {
    $m = Select-String -Path $ih -Pattern "const APPVER\s*=\s*'(v\d+)'" | Select-Object -First 1
    if ($m) { $ver = $m.Matches[0].Groups[1].Value }
  }
  if ($ver) {
    $vroot = Join-Path $bk 'versions'
    New-Item -ItemType Directory -Force -Path $vroot | Out-Null
    $vdir = Join-Path $vroot $ver
    if (-not (Test-Path $vdir)) {
      New-Item -ItemType Directory -Force -Path $vdir | Out-Null
      if (Test-Path $ih) { Copy-Item $ih (Join-Path $vdir 'index.html') -Force }
      if (Test-Path $bp) { Copy-Item $bp (Join-Path $vdir 'bot.py') -Force }
      $un = Join-Path $proj 'update_note.txt'
      $desc = ''
      if (Test-Path $un) { Copy-Item $un (Join-Path $vdir 'update_note.txt') -Force; $desc = (Get-Content $un -Raw -Encoding UTF8) }
      Set-Content -Path (Join-Path $vdir 'ОПИСАНИЕ.txt') -Value ("$ver  (создан $now)`r`n`r`n$desc") -Encoding UTF8
      $vzip = Join-Path $vroot ($ver + '_' + $stamp + '.zip')
      if (Test-Path $vzip) { Remove-Item $vzip -Force }
      Compress-Archive -Path (Join-Path $vdir '*') -DestinationPath $vzip -Force
      Add-Content -Path (Join-Path $bk 'backup_log.txt') -Value "$now  VERSION $ver -> $(Split-Path $vzip -Leaf)" -Encoding UTF8
      Write-Output "Version snapshot $ver -> $(Split-Path $vzip -Leaf)"
    }
  }
} catch { Write-Output "Version snapshot skipped: $_" }

# 4) месячный бэкап: каждое 11-е число (или вручную -Monthly) — отдельный датированный зип, ХРАНИТСЯ (прошлые месяцы не трогаются)
if ($Monthly -or (Get-Date).Day -eq 11) {
  $mzip = Join-Path $bk ("Muslimoon_MONTHLY_" + (Get-Date -Format 'yyyy-MM') + ".zip")
  Copy-Item $zip $mzip -Force
  Add-Content -Path (Join-Path $bk 'backup_log.txt') -Value "$now  MONTHLY -> $(Split-Path $mzip -Leaf)" -Encoding UTF8
  Write-Output "Monthly backup -> $mzip"
}

# 5) лог
$sz = [math]::Round((Get-Item $zip).Length / 1KB, 0)
Add-Content -Path (Join-Path $bk 'backup_log.txt') -Value "$now  OK  core=$($items.Count) formulas=$($formulas.Count) config=$($config.Count)  zip=${sz}KB" -Encoding UTF8
Write-Output "Backup OK $now (core=$($items.Count), formulas=$($formulas.Count), config=$($config.Count), zip=${sz}KB)"

# 6) УВЕДОМЛЕНИЕ ВЛАДЕЛЬЦУ (закон 17.06: бэкап — в уведомления/рабочий журнал, куда идут ошибки)
$verTxt = 'n/a'
if ($ver) { $verTxt = $ver }
$msg = "Бэкап $verTxt OK ($now): файлов $($items.Count), zip $sz КБ. Google Drive\Muslimoon_BACKUP (RECOVERY.zip + versions\)"
# 6a) мгновенный пуш на телефон владельца (ntfy)
try { Invoke-RestMethod -Uri 'https://ntfy.sh/kwe123' -Method Post -TimeoutSec 10 -Body ([System.Text.Encoding]::UTF8.GetBytes($msg)) | Out-Null } catch {}
# 6b) backup_note.txt → бот постит в рабочий журнал (LOG_CHAT) + владельцу в ЛС (как ошибки)
try { Set-Content -Path (Join-Path $proj 'backup_note.txt') -Value $msg -Encoding UTF8 } catch {}

# 7) #259/#261: ПРИСЛАТЬ САМ ФАЙЛ архива владельцу В ЛИЧКУ через бота (а не ссылку/путь).
#    Локально zip есть, токена бота локально НЕТ → заливаем zip на эндпоинт бота /api/backup_push,
#    бот делает send_document владельцу (OWNER) в ЛС. Приватно (внутри журналы, R42) — только владельцу.
#    Секрет берём из env MUSL_BACKUP_SECRET, иначе из локального gitignored-файла .backup_secret (НЕ попадает в репо/бэкап).
try {
  $secret = $env:MUSL_BACKUP_SECRET
  $secFile = Join-Path $proj '.backup_secret'
  if ([string]::IsNullOrWhiteSpace($secret) -and (Test-Path $secFile)) { $secret = (Get-Content $secFile -Raw -Encoding UTF8).Trim() }
  if (-not [string]::IsNullOrWhiteSpace($secret)) {
    $url = 'https://melodious-acceptance-production-1c9a.up.railway.app/api/backup_push'
    Add-Type -AssemblyName System.Net.Http | Out-Null
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(120)
    $form = New-Object System.Net.Http.MultipartFormDataContent
    $form.Add((New-Object System.Net.Http.StringContent($secret)), 'secret')
    $form.Add((New-Object System.Net.Http.StringContent($msg)), 'caption')
    $fs = [System.IO.File]::OpenRead($zip)
    $fc = New-Object System.Net.Http.StreamContent($fs)
    $fc.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('application/zip')
    $form.Add($fc, 'file', 'Muslimoon_RECOVERY.zip')
    $resp = $client.PostAsync($url, $form).Result
    $bodyTxt = $resp.Content.ReadAsStringAsync().Result
    $fs.Dispose(); $client.Dispose()
    Add-Content -Path (Join-Path $bk 'backup_log.txt') -Value "$now  SEND owner DM: HTTP $([int]$resp.StatusCode) $bodyTxt" -Encoding UTF8
    Write-Output "Backup file -> owner DM: HTTP $([int]$resp.StatusCode)"
  } else {
    Add-Content -Path (Join-Path $bk 'backup_log.txt') -Value "$now  SEND skipped: нет MUSL_BACKUP_SECRET / .backup_secret" -Encoding UTF8
    Write-Output "Backup file send skipped: задай MUSL_BACKUP_SECRET (env) или .backup_secret (файл)"
  }
} catch {
  try { Add-Content -Path (Join-Path $bk 'backup_log.txt') -Value "$now  SEND ERROR: $_" -Encoding UTF8 } catch {}
  Write-Output "Backup file send error: $_"
}
