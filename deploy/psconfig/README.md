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

**この症状は実際に起きた。** LG Gram に testpoint コンテナを立てた時点で `~/psconfig` が空のまま
だったため、agent は `activating`（`status=1/FAILURE` のクラッシュループ）から抜けられずにいた。
`docker ps` はコンテナを `Up` と表示し、`pscheduler troubleshoot` もオールOKを返すので、
**agent だけが死んでいることは `systemctl is-active psconfig-pscheduler-agent` を見ないと分からない**。
2026-07-30 の pSConfig 切替で3ファイルを配って初めて `active` になった（`experiments/w3-notes.md` Step 10）。

## 配置

**測定ノードは LG Gram（192.168.1.102）。** メッシュ定義は**3ノード全部**に配る。
VM・RasPi もそれぞれ自分が source 側になるタスクを自分で作るため、定義がずれると
片方向だけ古い測定が残る。

```bash
# LG Gram（測定ノード）
scp home-lab-mesh.json pscheduler-agent.json pscheduler-agent-logger.conf \
  dev@192.168.1.102:~/psconfig/
ssh dev@192.168.1.102 'mkdir -p ~/psconfig/{archives.d,pscheduler.d,transforms.d}'

# RasPi（LAN の対向）
scp home-lab-mesh.json pscheduler-agent.json pscheduler-agent-logger.conf \
  unpeeled@raspi-testpoint.local:~/psconfig/
ssh unpeeled@raspi-testpoint.local 'mkdir -p ~/psconfig/{archives.d,pscheduler.d,transforms.d}'

# VM（現在はどのグループにも属さず測定を持たない。ロールバック手段として定義だけ合わせておく）
limactl shell perfsonar-vm bash -lc '
  cp /Users/dev/src/perfsonar-otel-bridge/deploy/psconfig/{home-lab-mesh.json,pscheduler-agent.json,pscheduler-agent-logger.conf} ~/psconfig/
  mkdir -p ~/psconfig/{archives.d,pscheduler.d,transforms.d}'
```

**反映の順序は「新しい測定を立ち上げてから古い方を畳む」**（LG Gram → RasPi → VM）。
逆順にすると欠測の窓ができる。過渡期に数分間の二重測定が起きるが、これは意図的なトレードオフ。

反映（コンテナ再作成は不要）:

```bash
docker exec perfsonar-testpoint systemctl restart psconfig-pscheduler-agent
docker exec perfsonar-testpoint psconfig pscheduler-tasks   # 生成されたタスクを確認
```

**メッシュ変更の反映に restart が必須かは未確認。** 運用上の慣習として restart しているが、
agent が自動で再取得するかどうかは実装を追っていない。

## 検証

```bash
docker exec perfsonar-testpoint psconfig validate /etc/perfsonar/psconfig/home-lab-mesh.json
```

**restart の前に必ず validate する。** agent が既にクラッシュループしている状態で不正な定義を
入れて restart すると、直そうとしている `status=1/FAILURE` を再発させるだけになる。

`psconfig pscheduler-tasks` は agent が1回走り終えるまで
`Unable to find last guid in ... psconfig-pscheduler-agent.log` を返す。restart 直後に
空振りしても異常ではない（LG Gram では2分弱かかった）。

## ハマりどころ

- **`latency` の spec に `protocol` を書くなら `"schema": 4` が必須。** 省略すると spec schema v1 が
  使われ `Additional properties are not allowed ('protocol' was unexpected)` で validate に落ちる。
- **pSConfig の schedule は `repeat-cron` に対応しない。** pScheduler 単体は `--repeat-cron` を
  持つが、pSConfig の `ScheduleSpecification` は `start`/`repeat`/`slip`/`sliprand`/`until`/`max-runs`
  のみで `additionalProperties: false`。時刻を固定したいときは絶対時刻の `start` + `repeat: P1D` を使う。
  iperf3 を深夜帯（02:00-06:00 JST）に限定する規約はこの方法で満たしている。
- `psconfig remote add` は URL を `--quiet` より先に置くこと。順序を誤ると
  `unrecognized arguments` になる。
