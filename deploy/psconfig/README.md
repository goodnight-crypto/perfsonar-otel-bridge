# pSConfig 設定

このディレクトリが**正**。testpoint コンテナの `/etc/perfsonar/psconfig` はホスト側ディレクトリを
バインドマウントしているので、ここのファイルをホストへ配ればコンテナを作り直さずに反映できる。

| ファイル | 役割 |
|---|---|
| `home-lab-mesh.json` | 測定定義（アドレス・グループ・テスト・スケジュール・アーカイブ・タスク） |
| `pscheduler-agent.json` | エージェント設定。上記メッシュ定義をローカルファイルとして参照する |
| `pscheduler-agent-logger.conf` | ロガー設定。イメージ既定のコピー |

## 重要: 空ディレクトリのマウントは既定ファイルを隠す

`run-testpoint.sh` はホストの `~/psconfig` を `/etc/perfsonar/psconfig` にマウントする。
このホスト側が空だと、**イメージに入っている `pscheduler-agent.json` と
`pscheduler-agent-logger.conf` が隠れて `psconfig-pscheduler-agent` が起動できない**
（`status=1/FAILURE` でクラッシュループする）。ホスト側に必ずこの3ファイルを置くこと。

## 配置

```bash
# VM
limactl shell perfsonar-vm bash -lc '
  cp /Users/dev/src/perfsonar-otel-bridge/deploy/psconfig/{home-lab-mesh.json,pscheduler-agent.json,pscheduler-agent-logger.conf} ~/psconfig/
  mkdir -p ~/psconfig/{archives.d,pscheduler.d,transforms.d}'

# RasPi
scp home-lab-mesh.json pscheduler-agent.json pscheduler-agent-logger.conf \
  unpeeled@raspi-testpoint.local:~/psconfig/
ssh unpeeled@raspi-testpoint.local 'mkdir -p ~/psconfig/{archives.d,pscheduler.d,transforms.d}'
```

反映（コンテナ再作成は不要）:

```bash
docker exec perfsonar-testpoint systemctl restart psconfig-pscheduler-agent
docker exec perfsonar-testpoint psconfig pscheduler-tasks   # 生成されたタスクを確認
```

## 検証

```bash
docker exec perfsonar-testpoint psconfig validate /etc/perfsonar/psconfig/home-lab-mesh.json
```

## ハマりどころ

- **`latency` の spec に `protocol` を書くなら `"schema": 4` が必須。** 省略すると spec schema v1 が
  使われ `Additional properties are not allowed ('protocol' was unexpected)` で validate に落ちる。
- **pSConfig の schedule は `repeat-cron` に対応しない。** pScheduler 単体は `--repeat-cron` を
  持つが、pSConfig の `ScheduleSpecification` は `start`/`repeat`/`slip`/`sliprand`/`until`/`max-runs`
  のみで `additionalProperties: false`。時刻を固定したいときは絶対時刻の `start` + `repeat: P1D` を使う。
  iperf3 を深夜帯（02:00-06:00 JST）に限定する規約はこの方法で満たしている。
- `psconfig remote add` は URL を `--quiet` より先に置くこと。順序を誤ると
  `unrecognized arguments` になる。
