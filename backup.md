# Backup

Primary backup: this project lives in version control at https://github.com/zmirburger/ai-leaderboard. Every daily refresh creates a commit, so history is preserved automatically.

## Optional local backup

To mirror the folder elsewhere (OneDrive, iCloud, external drive):

PowerShell:
```powershell
Copy-Item -Path "C:\Users\User\cowork\ai_leaderboard" -Destination "C:\Users\User\OneDrive\Backups\ai_leaderboard" -Recurse -Force
```

Run monthly or after manual config edits.

## Restore from GitHub

If the local folder is wiped:
```powershell
cd C:\Users\User\cowork
git clone https://github.com/zmirburger/ai-leaderboard.git
```
