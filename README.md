# Decathlon HRM Belt OBS Overlay

Windows 11'de Decathlon Bluetooth/ANT+ nabiz kemerini Bluetooth Low Energy uzerinden okuyan, OBS icin yerel overlay veren kucuk Python uygulamasi.

## Ne yapar?

- BLE Heart Rate Service (`0x180D`) ve Heart Rate Measurement (`0x2A37`) bildirimi okur.
- OBS Browser Source icin `http://127.0.0.1:8765/overlay` adresini sunar.
- Boy, kilo, yas ve cinsiyet ayarlarini kaydeder.
- Nabiz, sure ve kullanici bilgilerine gore tahmini kalori yakimini canli hesaplar.
- Nabiz bolgesine gore renk degistirir: dinlenme acik mavi, isinma turkuaz, yag yakimi sari, aerobik turuncu, anaerobik koyu turuncu, maksimum koyu kirmizi.
- Her yayin icin otomatik kayit tutar ve eski kayitlari rapor olarak gosterir.
- Kemer yaninizda degilken test etmek icin demo modu vardir.

## Kurulum

1. Windows Bluetooth'u acin.
2. Nabiz kemerini takin veya elektrotlarini hafif islatin; kemer takili degilse uyumaya devam edebilir.
3. Bu klasordeki `run.bat` dosyasini cift tiklayin.
4. Acilan terminalde su adresleri gorunecek:

```text
Ayar ekrani:   http://127.0.0.1:8765/
OBS overlay:  http://127.0.0.1:8765/overlay
```

`run.bat`, once Python 3.14 ile sanal ortam kurmayi dener. Bilgisayarda Python launcher farkliysa ayni klasorde su komutlar da kullanilabilir:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## Kullanım

1. Ayar ekranini acin: `http://127.0.0.1:8765/`
2. Boy, kilo, yas ve cinsiyet alanlarini doldurup kaydedin.
3. `Tara` dugmesine basin.
4. Decathlon/HRM/Heart Rate olarak gorunen cihazi secin.
5. `Baglan` dugmesine basin.
6. Nabiz degeri gelince kalori ve sure otomatik akar.

Demo modu, OBS ekranini kemer olmadan denemek icindir. Gercek kemer baglantisi icin demo aciksa `Kes` dugmesine basin veya dogrudan `Baglan` dugmesini kullanin.

## Yayın kayıtları ve raporlar

- `Baglan` dugmesine bastiginizda otomatik yeni bir yayin kaydi baslar.
- Nabiz verisi geldikce kayit dosyasi otomatik guncellenir.
- Yayini bitirirken `Kaydi durdur` dugmesine basin; kayit kapanir ve eski kayitlar listesine duser.
- Ayar ekranindaki `Yayin kayitlari` bolumunden eski kayitlara tiklayabilirsiniz.
- Rapor ekraninda toplam sure, kalori, ortalama/en dusuk/en yuksek nabiz, nabiz grafigi ve bolgelere gore sure dagilimi gorunur.
- Aktif kayit varken ayar sayfasini kapatmaya calisirsaniz tarayici once `Kaydi durdur` ile kaydetmeniz icin uyarir.
- `Sifirla` dugmesi aktif kaydi kapatir ve yeni bir kayit baslatir; aktif kayit yoksa sadece ekrandaki sure/kalori sayacini sifirlar.

Kayitlar bilgisayarda su klasorde tutulur ve GitHub'a yuklenmez:

```text
data/sessions/
```

## OBS Browser Source

1. OBS'de sahnenize `Browser` kaynagi ekleyin.
2. `Local file` secenegini kapali birakin.
3. URL alanina sunu girin:

```text
http://127.0.0.1:8765/overlay
```

4. Genislik/yukseklik icin onerilen deger:

```text
Width: 520
Height: 820
```

5. OBS'de arka plan seffaf gorunur; overlay kendi yari saydam panelini cizer.

## Notlar

- ANT+ okumasi icin ayri ANT+ USB dongle ve farkli kutuphane gerekir. Bu uygulama Decathlon kemerin Bluetooth Low Energy tarafini kullanir.
- Kalori hesabi tibbi/laboratuvar hassasiyetinde degildir; yayin ve antrenman takibi icin makul bir tahmindir.
- Temel nabiz-kalori hesabi Keytel tipi kalp atis hizi denklemini kullanir. Boy bilgisi Mifflin-St Jeor dinlenme yakimi alt sinirina dahil edilir.
- BLE paketi olarak sadece `bleak` kullanilir. `bleak`, Windows 11 BLE destegi saglar ve PyPI uzerinde Python `>=3.10` ister.

## Sorun giderme

- Cihaz listede yoksa kemeri takin, elektrotlari islatin, 10 saniye bekleyip tekrar tarayin.
- Windows Bluetooth ayarlarindan kemeri daha once eslestirdiyseniz, baglanti sorununda cihaz kaydini kaldirip tekrar deneyin.
- Terminalde `Bleak paketi yuklu degil` yazarsa `run.bat` dosyasini yeniden calistirin.
- Baska bir uygulama kemere bagliysa once o uygulamayi kapatin; BLE kalp kemerleri ayni anda sinirli sayida baglanti kabul edebilir.
- Port doluysa:

```powershell
.\.venv\Scripts\python.exe app.py --port 8766
```

OBS URL'sini de `http://127.0.0.1:8766/overlay` yapin.
