# ISUCON14: 品質保留の修正と再発

Practice study: `kaizen-effect-study-20261017`。既知問題、アプリ1台c5.large、
bench c5.xlarge、Go/SQLだけを変更、3論理Codex actor、45分。
比較群は未実施で、この結果だけではpluginの優位性を示さない。

- 初期baseline 687/929。時間内9実験中3採用、5保留、1不採用。
- index群は速度が伸びたがtimeout等で保留。ownerの取得範囲の修正と合わせ、
  3,181/3,487・無警告の2計測で採用した。
- parameter interpolationは4,562/4,202でCODE26が出て保留。
  coordinate timestampをcommit直前へ移す変更と合わせ、7,917/8,615・無警告で採用した。
- 採用版`c9b8b3380f1b2151c9a6c15b45393c4f48def93d`の再起動後固定3計測は
  8,090/7,816/8,124、全て公式PASS。ただし1回はCODE26が3件、分母不明。
  追加品質確認はunknownであり、修正により完全解決したとは扱わない。
- nearby N+1改善は7,768/8,103で現在stableより中央値が低かった。
  局所的なクエリ削減が最終スコアの改善になるとは限らない。

次の調査は、再発したCODE26の計測時刻・commit可視性・遅延分布・分母を取得し、
初回保留、修正、最終再発を別々の根拠として比較する。現在の採用履歴は維持する。
再試行は新しい仮説・修正・計測枠の見通しがある場合に行う。
既知の改善順序を別問題へそのまま適用せず、当日の観測と仕様を先に確認する。

生の根拠は同studyの`controller/analysis-kaizen.json`、
`controller/final/kaizen/result.json`、
`kaizen/integration/.kaizen/experiments/003-indexes-owner-filter/record.json`、
`006-interpolate-coordinate-timestamp/record.json`。
これは問題固有の知識であり、その環境の操作Skillや固定の改善手順ではない。
