# Yamane Laboratory website

公開先：<https://yamane130.github.io/yamane-lab-site/>

書誌情報は [山根達郎のresearchmap](https://researchmap.jp/t_yamane) で管理し、取得した公開データを静的HTMLへ書き出します。サイト側で題目・著者・掲載誌・DOIを二重入力する必要はありません。

## この修正版でできること

- トップページに最近の論文10件、論文一覧に全件を表示します。刊行予定の論文も含め、researchmapの題目・著者・掲載誌・巻号・頁または論文番号・年を反映します。要旨や説明欄は一覧に転載しません。
- 論文・研究プロジェクト・受賞情報をHTMLに書き込むため、JavaScriptを実行しなくても閲覧できます。
- DOIが `identifiers.doi` 以外に `see_also` のURLに入っている場合もリンクにします。
- researchmapを正常に取得した日時を表示します。論文の出版日とサイトの取得日は区別します。
- 公開可能な論文PDFを追加すると、該当する論文の下に原稿版・PDFリンク・権利注記を表示できます。

現時点の `manuscripts.json` は空です。この修正版には論文PDFは含まれておらず、サイトの変更だけで各論文がオープンアクセスになるわけではありません。

## 初回の公開設定

1. この変更をリポジトリの `main` に反映します。配布ZIPを使う場合は展開して `yamane-lab-site/` 内のファイルを既存リポジトリへ反映します。ZIP自体をGitHubへ置いてもサイトは更新されません。`.github/workflows/pages.yml` も含めてください。旧 `yamane-researchmap.js` は参照を廃止したため削除できます。
2. GitHubの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
3. **Actions → Publish lab site → Run workflow** で `main` を選んで実行します。
4. 成功後、公開サイトの論文一覧と「書誌情報の取得日時」を確認します。

最初は同梱の `researchmap_data.json` を使って公開します。API同期は次の設定を有効にするまで動きません。これは、既存データだけでもビルド・表示を確認できるようにするためです。

設定方法の根拠：[GitHub Pagesのカスタムワークフロー](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。

配布ZIPにはレビュー用の `changes.patch` も含みます。2025年11月29日の `23a295716a339da253aefd3edc161f980890339e` を基準とした差分です。既存のcloneで差分を適用する場合は、新しい作業ブランチを作り、`git apply --check /path/to/changes.patch` で適用可能なことを確認してから `git apply /path/to/changes.patch` を実行してください。基準以降に別の変更がある場合、無理に上書きせず差分を確認してください。

## researchmapの更新を反映する

researchmap Web APIの継続利用について、[公式の利用申請案内](https://researchmap.jp/public/other-document/application)と利用条件を確認してください。すでに利用手続きが済んでいれば、その条件に合わせて設定します。匿名で公開データを取得できることと、継続的なAPI利用の手続きは別です。

GitHubの **Settings → Secrets and variables → Actions → Variables** で、次のrepository variableを設定します。

| Name | Value |
| --- | --- |
| `RESEARCHMAP_SYNC` | `true` |

有効にすると、`main` への変更、`main` を指定した手動実行、日次スケジュールで最新の公開データを取得してサイトへ反映します。pull requestの検証時にはAPIに接続しません。

- 通常：researchmapを更新すると、次回の定期実行でサイトにも反映されます。
- 早く反映したい場合：**Actions → Publish lab site → Run workflow → main** を実行します。
- 同期を無効にした場合：手動実行や `main` への変更では、リポジトリに保存されたJSONからサイトを生成します。researchmapから再取得はしません。実行結果のSummaryにもその旨を表示します。

定期実行は毎日 **05:17 JST（20:17 UTC）** の設定ですが、GitHubの混雑等によって遅れたり実行されなかったりする場合があります。また、公開リポジトリでは**リポジトリ上の活動が60日間ないと定期実行が自動停止**します。researchmapの更新や定期実行だけでは、この制限を避けられるとは限りません。長期間GitHubを更新していない場合は、Actions画面で停止状態を確認し、必要に応じて再有効化してください。根拠：[GitHub Actionsのschedule仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

API取得・データ検証・ビルドに失敗したときは、新しいサイトを公開しません。以前に正常公開できたサイトがそのまま残ります。エラーはActionsの実行ログで確認できます。

ワークフローはリポジトリのJSONやHTMLに自動コミットしません。APIから取得したデータは、その実行で作る公開サイトに反映されます。公開サイトの取得日時が現在のデータ鮮度を示します。後から同期を無効にすると、再びリポジトリの保存データを使うため、必要なら無効化前に下記のローカル更新を行ってJSONをコミットしてください。

## 著者稿PDFを公開する

このリポジトリ自体が公開されています。**公開可能になっている原稿だけ**を追加してください。エンバーゴ中のPDFは、リンクを付けなくてもリポジトリへコミットした時点で公開されます。

1. 対象の出版社・掲載誌・契約で公開可能な原稿版と時期を確認します。著者最終稿と出版社版PDFは区別します。
2. 許可されたPDFを `papers/<researchmap ID>/accepted-manuscript.pdf` などのパスへ置きます。
3. `manuscripts.json` の `papers` に、その論文のresearchmap IDとPDF情報を追加します。
4. サイトをビルドしてリンクを確認し、変更をGitHubへ反映します。

researchmap IDは、論文のresearchmap詳細URLの末尾、または `researchmap_data.json` 内の該当論文の `rm:id` で確認できます。

以下は形式の説明用です。ID・パス・注記を実際の論文に置き換えてください。

```json
{
  "schema_version": 1,
  "papers": {
    "12345678": {
      "pdf": "papers/12345678/accepted-manuscript.pdf",
      "version": "accepted_manuscript",
      "rights_statement": "出版社の条件に従った権利注記をここへ記載"
    }
  }
}
```

使用できる原稿版は `accepted_manuscript`（著者最終稿）、`published_version`（出版社版）、`preprint`（プレプリント）です。`published_version` を選ぶだけで再配布が許可されるわけではありません。出版社の指定する引用・DOI・著作権表示はPDF内にも必要に応じて記載してください。

任意の `available_from` に `YYYY-MM-DD` 形式の公開可能日を記録できます。未来の日付の原稿はビルドエラーになります。このチェックは公開リポジトリへのアップロードを取り消したり、原稿を非公開にしたりする機能ではありません。解禁前のPDFを保存する用途には使わないでください。

書誌情報はresearchmapから取得するので、`manuscripts.json` に題目・著者・掲載誌を重複登録する必要はありません。論文のIDが変わるような削除・再登録をした場合は、PDF側のIDも確認してください。

researchmapから論文を削除・非公開化する場合は、`manuscripts.json` の対応項目も整理してください。公開する書誌データにないIDが残ると、整合性エラーで更新を止め、以前の公開サイトが残ります。PDFの公開を取りやめる場合は、PDFファイル自体と公開結果も確認してください。この仕組みは公開Gitリポジトリの過去の履歴を消去するものではありません。

## Google Scholarについて

Googleの個人著者向けの案内に沿って、静的な論文一覧から各論文の全文PDFへ直接リンクします。Google Scholar用のアップロード機能を使う必要はありません。

PDFは文字を検索・抽出できる形式にし、冒頭に論文タイトルと著者名、末尾に参考文献を含めてください。Googleの案内には5 MB以下という条件もあります。別の論文を1つのPDFにまとめず、論文ごとのURLを維持します。

現時点では原稿と著者要旨がないため、論文別HTMLや `citation_*` メタタグは追加していません。全文PDFの公開後、必要に応じて実際の要旨を載せた論文別ページへ拡張できます。論文一覧全体を1本の論文としてメタデータ登録することはしません。

サイトの公開とGoogle Scholarでの収録・無料全文の認識には時間差があります。収録や表示の変更は保証できません。確認するときは対象論文のタイトルで検索し、追加したPDFが候補になっているかを調べます。

根拠：[Google Scholar Inclusion Guidelines](https://scholar.google.com/intl/en/scholar/inclusion.html)。

## ローカルでの更新と確認

Python 3.12を使用します。ビルドとデータ取得に外部Pythonパッケージは不要です。

保存済みデータからルートのHTMLを更新する場合：

```bash
python build_site.py
```

APIから再取得して更新する場合：

```bash
python fetch_researchmap.py
python build_site.py
```

GitHub Pagesと同じ公開用フォルダを生成して確認する場合：

```bash
python build_site.py --output-dir _site
python -m http.server 8000 --directory _site
```

ブラウザで `http://localhost:8000/` を開きます。確認用サーバーは `Ctrl+C` で終了できます。公開用フォルダに今回の公開対象ではないファイルが残っている場合は、ビルドを停止します。たとえばPDFを公開対象から外した後は、新しい空のフォルダを出力先にするか、前回の生成物であることを確認してから古い出力フォルダを整理してください。

`_site` には、HTML・CSSと `manuscripts.json` で指定したPDFだけを公開用に含めます。Pythonスクリプト・テスト・書誌JSONを丸ごと公開成果物へコピーする構成にはしていません。ただし、これらのソースファイル自体は公開GitHubリポジトリで閲覧できます。

データ取得では、全カテゴリを取得・検証した後にJSONを置き換えます。取得途中の失敗、不明な返却形式、不完全なページ分割、既存データがあるカテゴリの予期しない0件化では、保存済みJSONを上書きしません。意図的にカテゴリの全データを非公開化・削除した場合は、この0件保護により更新が止まるので、内容を確認して保存データを整理してください。
