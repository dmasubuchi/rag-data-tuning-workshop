# Windows PC の設定

参加者の PC で、最初に1回行います。

## 1. 確かめる

1. [ ] ネットワークにつながっている
2. [ ] GitHub で、研修の Repo を開ける（Repo の URL は進行役から聞きます）
3. [ ] clone できる：`git clone <Repo の URL>`
4. [ ] Python（3.11 か 3.12）：`python --version`
5. [ ] ライブラリ：clone したフォルダーで `pip install -r basic/requirements.txt`
6. [ ] az：`az version`
7. [ ] 連絡の場所：進行役が案内するチャットなどに入る

コマンドは PowerShell で実行します。macOS・Linux の bash でも、同じコマンドで動きます。

### 入っていないとき

PowerShell で、足りないものだけ実行します。入れたら PowerShell を開き直します。

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.12
winget install -e --id Microsoft.AzureCLI
winget install -e --id Microsoft.VisualStudioCode
```

winget が使えないときは、公式サイトから入れます。Git（`https://git-scm.com`）、Python（`https://www.python.org/downloads/`。「Add python.exe to PATH」にチェック）、az（`https://aka.ms/installazurecliwindows`）、VS Code（`https://code.visualstudio.com`）

## 2. VS Code で資料を読む

1. [ ] 拡張機能（`Ctrl+Shift+X`）で「Markdown Preview Mermaid Support」を検索して入れる（図が表示されるようになる）
   - コマンドなら：`code --install-extension bierner.markdown-mermaid`
2. [ ] `.md` を開いて `Ctrl+Shift+V` でプレビューする（横に並べるなら `Ctrl+K` のあとに `V`）

GitHub の画面で読むときは、何も入れなくても図が表示されます。

## 次の手順

[Azure の準備](azure-setup.md)
