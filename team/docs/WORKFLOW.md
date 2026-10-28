# 繰り返し作業を競技中に改善する

練習で汎用Skillの精度を高め、競技では本番環境へ特化する。
[improve-workflow](../../skills/improve-workflow/SKILL.md)を使う。
モードと、汎用/問題・環境固有という適用範囲を別々に判定する。

| モード | 行うこと | 完了条件 |
|---|---|---|
| practice・汎用 | 手順・Skillと補助ツールを自己改善し、別問題/fixtureでも検証する | 汎用プラグインmainへ反映し、精度を高める |
| practice・問題/環境固有 | 実例、頻度、手間、提案、検証方法を共有knowledgeのlessonsへ保存 | 問題固有の実装・Skill生成・配布はしない |
| competition | 回収できる反復作業をscript化・Skill化する。本番環境固有の手順も対象 | 検証してチーム用プラグインmainへ統合し、読み込みSHAと短縮を確認する |
| 未指定 | ナレッジ保存 | 競技と推測して配布しない |

人間の指定したモードを使い、セッション記録に残す。現行CLIがすべての
操作を機械的にモード制限する仕組みではない。
「失敗ログから原因を調べる手順」「安全な結果集計」は汎用候補。
「この問題のDBスキーマに対するSQL」「このチームのホスト配置・デプロイ手順」は
固有候補。ホスト名だけ引数にした固有手順を汎用と呼ばない。

人間から運用上の助言を受けたら、AIはその都度、今回だけの方針か、他の問題でも使える
手順・Skillの改善かを自律的に判断する。既存手順の適合箇所を先に確認し、重複を増やさず、
再発防止や判断精度に効く最小差分をこの手順で検証・共有する。助言のたびに一律の承認待ちや
plugin変更を作らない。固有の知見はknowledgeへ残し、汎用変更と実際の配布・読込状態を区別する。

### 助言の判断を台帳へ残す

新たな人間の助言ごとに、まず共有台帳へ`feedback-add`で原文の参照先・要約・担当を登録し、
既存手順への適合を確認して`feedback-decide`で判断・理由・根拠を残す。同じ参照先と要約の
再登録は既存項目を返す。これは起動中のAIが行う手順であり、人間の発言を自動捕捉するhookや
Codex adapterは実装していない。`queue`/`status`の`feedback_pending`で未判断を確認し、
`feedback_deferred`の次アクションも作業境界で見直す。未判断は通常の候補作業を停止するgateではない。

```bash
python3 "$K/scripts/team/control.py" feedback-add --agent "$KAIZEN_SESSION" \
  --source-ref PRIVATE_MESSAGE_REFERENCE --summary '他の問題にも適用できる運用上の助言'
python3 "$K/scripts/team/control.py" feedback-decide --agent "$KAIZEN_SESSION" --id F-0001 \
  --decision existing --reason '既存手順が同じ条件と動作を定義している' --artifact team/docs/PIPELINE.md
python3 "$K/scripts/team/control.py" feedback-list --pending
```

判断は`adopt`（必要な反映を選択しtask/commitへつなぐ）、`existing`（既存の適合箇所）、
`defer`（見送る理由と調査・修復などの`--next-action`必須）、`reject`（採らない根拠）から選ぶ。
すべて理由と`--artifact`を必須とし、担当だけが更新する。更新前の判断もeventsへ残る。
`adopt`はコード採用・配布完了の証拠ではない。通常の検証、release、実読確認まで別に追跡する。
原文・privateな固有情報は共有private DBとアクセス可能なartifactに保持し、汎用pluginのGitへ写さない。

新しいwarningや品質保留を単なる終了理由にせず、再現・原因調査・修復案・実現性と総費用を
比較し、続ける次アクションまたは見切る根拠を残す。この運用への助言もfeedbackへ登録する。
品質の事実と候補の修復は元のquality hold/taskへ記録し、feedbackの判断だけで保留を解除しない。

## 時間を回収できる作業を選ぶ

練習・本番とも、検証の効率と素早い実戦feedbackを優先する。plugin変更は変更した契約と
最低限の稼働品質を確認して速く配布し、必要性のない全体テストや完璧さを待たない。
具体的な失敗・影響範囲がある場合に確認を広げる。アプリの正しさ・環境排他は維持する。

コマンド反復・ログ集計は小さなscript、判断や手動手順を含む作業はSkillにする。
既存の道具を再利用し、新しい管理層や毎回の包括レビューを増やさない。
候補の反復準備には[prepare-candidate](../../skills/prepare-candidate/SKILL.md)と
[PIPELINE](PIPELINE.md)を使い、実装・関連検証・引渡しを一括して自走する。
実装中に別担当が仕様・次候補を調べ、計測中も独立した準備を続ける。
`残り回数 × 1回の短縮時間 − 実装・検証・配布・復旧余裕`を実例で見積もる。
例: 60秒の整形が残り12回、5分で実装・検証・配布できるなら回収候補。
残り1回の操作を10分かけて自動化するなら、手作業と記録を選ぶ。
練習の汎用改善は、今回の残り回数だけでなく別問題への再利用と精度向上で判断する。

## 別のGit履歴で配布する

1. toolingタスクに根拠と範囲を登録する。編集可能なプラグインcloneの
   `<github-login>/tooling/<task-or-topic>`で作業し、インストールcacheを改変しない。
2. 入出力・対象・失敗動作・戻し方を決め、fixtureと指定チェックで検証する。
3. 同時に1人のプラグイン統合担当が、最新origin/mainとcleanなmainを確認し、
   コミットを統合、再検証して通常pushする。PR待ちとforce-pushは使わない。
   mainが進んだら取り込み直して検証する。
   本番固有のSkillと競技情報はチーム専用の非公開プラグインmainへ置く。
   汎用upstreamが公開ならprivate fork/packで運用し、競技中に公開しない。
4. 配布SHA、checks、戻し先SHAを共有する。各PCと共通ホストは処理の区切りで
   更新する。新セッションが必要なら実際の起動・読み込み後に更新済みと記録する。
   実行中スクリプトや進行中実験の計測コアを差し替えない。
5. 競技ソースのmain、stable、実験記録は元の統合手順で管理する。

合意した操作範囲・品質・排他・復旧条件を守る道具の改善はAIが検証して進める。
未検証や時間対効果の不確実性はAIが調べ、合意を超える目的・権限・不可逆操作・重大な
残余リスクの選択だけを[POLICY](../POLICY.md#adoption-and-human-judgment)に従って人間へ渡す。
Skill追加は手動必須操作の自動化許可やガードの回避を意味しない。
[証拠票](../templates/WORKFLOW.md)を使い、実際の回収時間を確認する。
