# 採用時の実資源を候補の測定へ結び付ける

対象: plugin 0.7.3 / source `5ed9f70`を基準としたfake remote検証。

人間判断待ちでrecoverすると、安定コードとともにschemaも戻る。承認後の候補コード再deployは
schemaの初期化を保証しない。以前のcandidate sample同士が同じfingerprintでも、現在の対象が
その資源を持っていなければ、測定結果を根拠に採用できない。

修正前は次を実際のscripts経路で再現した。

- schema Bで候補を2計測し、recoverでAへ戻し、候補コードのみ再deployした。
- human参照付きrecordがexit 0でpromoteし、schema Aを新stable bundleへcaptureした。
- probe故障でも先にmain/STABLE_REVを進め、bundle captureで初めて失敗した。

0.7.4ではmain/STABLE_REV更新直前のread-only probeを、同candidate SHAを測った
非観測sampleすべてと完全照合する。空probeは既存の空fingerprintと互換にし、
probe故障・測定資源との不一致は採用前に拒否する。

`tests/test_adoption_resources.py`は修正前4件中2件が失敗し、修正後に以下を確認する。

- 人間待ちの復旧後に資源が異なれば、main・stable・開いた実験・元sampleを保持して拒否する。
- 追加の初期化付きベンチで候補資源が戻れば、元sampleを削除せず採用できる。
- probe故障はmain/STABLE_REVを進めず拒否する。
- probe未設定の既存運用は維持する。

これはfake remoteでの機構確認。稼働中の実測用pluginは更新せず、実機への反映は
実験・予約・復旧待ちのない境界で行う。probeの対象外にある資源の一致は証明しない。
