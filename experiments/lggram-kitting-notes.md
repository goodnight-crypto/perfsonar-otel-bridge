ダウンロードしたファイル名
ubuntu-24.04.4-live-server-amd64.iso

```
echo "e907d92eeec9df64163a7e454cbc8d7755e8ddc7ed42f99dbc80c40f1a138433 *ubuntu-24.04.4-live-server-amd64.iso" | shasum -a 256 --check
ubuntu-24.04.4-live-server-amd64.iso: OK
```

```
sudo dd if=/Users/jun/Downloads/ubuntu-24.04.4-live-server-amd64.iso of=/dev/rdisk7 bs=4m
811+1 records in
811+1 records out
3405469696 bytes transferred in 240.385804 secs (14166684 bytes/sec)
```

```
diskutil eject /dev/disk7
```