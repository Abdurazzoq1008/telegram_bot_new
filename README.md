# Kun.uz yangiliklarini Telegram kanaliga yuborish

Bot Kun.uz'ning o‘zbekcha RSS lentasini tekshiradi va kanalga faqat yangi
xabarlarning rasmi, sarlavhasi, qisqa tavsifi, bo‘limi, chop etilgan vaqti va
manba havolasini yuboradi.

## Ishga tushirish

1. Telegram'da [@BotFather](https://t.me/BotFather) orqali bot yarating va token oling.
2. Botni kanalingizga administrator qilib qo‘shing, unga xabar yuborish huquqini bering.
3. PowerShell'da token va kanal manzilini kiriting. Ochiq kanal uchun `@kanal_nomi`,
   yopiq kanal uchun `-100...` ko‘rinishidagi kanal ID'sini ishlating:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN="BotFather bergan token"
   $env:TELEGRAM_CHANNEL_ID="@kanal_nomi"
   python main.py
   ```

Bot ishlayotgan paytda PowerShell oynasi ochiq turishi kerak. Doimiy ishlashi
uchun uni uzluksiz ishlaydigan kompyuter yoki serverda ishga tushiring.
To‘xtatish uchun `Ctrl+C` bosing; terminalda `Bot to‘xtatildi.` xabari chiqadi.

## Muhim sozlamalar

- Birinchi ishga tushishda RSS'dagi mavjud xabarlar yuborilmaydi — ular eski
  deb belgilanadi. Shundan keyin chiqqan yangiliklargina yuboriladi.
- Tekshirish oralig'i standart holatda 60 soniya. O'zgartirish uchun, masalan:
  `$env:POLL_INTERVAL_SECONDS="120"`.
- Ko'rilgan xabarlar `seen_articles.json` faylida saqlanadi. Bu faylni o'chirsangiz,
  keyingi ishga tushishda mavjud yangiliklar qaytadan eski deb belgilanadi.

## Test

```powershell
python -m unittest discover -s tests
```

## Xabar yuborilmasa

Terminalda chiqadigan `Telegram API xatosi` sababini tekshiring. `Chat not found`
chiqsa, kanal manzili (`@kanal_nomi` yoki `-100...` ID) to‘g‘ri ekanini va bot
kanalga administrator qilib qo‘shilganini tekshiring. `not enough rights` chiqsa,
bot administratori uchun xabar yuborish huquqini yoqing. Tokenni hech kimga
yubormang.
