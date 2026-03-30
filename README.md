# download-images-fb-post

Extension Coc Coc/Chrome de tai tat ca anh tu mot bai post Facebook theo link ban nhap vao.

## Cach dung

1. Vao `coccoc://extensions` trong Coc Coc.
2. Bat `Developer mode`.
3. Bam `Load unpacked`.
4. Chon thu muc [extension](d:/GITHUB/download-images-fb-post/extension).
5. Bam icon extension `FB Post Image Downloader`.
6. Dan link bai post Facebook vao popup.
7. Nhap `File name prefix` neu muon, vi du `du_lich_da_lat`.
8. Bam `Download Images`.

Extension se tu mo dung link bai post o background tab, quet anh, roi tai ve thu muc download cua trinh duyet trong folder `facebook-post-images`.

Vi du ten file sau khi tai:

- `du_lich_da_lat_001.jpg`
- `du_lich_da_lat_002.jpg`
- `du_lich_da_lat_003.jpg`

## Cau truc extension

- [manifest.json](d:/GITHUB/download-images-fb-post/extension/manifest.json)
- [popup.html](d:/GITHUB/download-images-fb-post/extension/popup.html)
- [popup.js](d:/GITHUB/download-images-fb-post/extension/popup.js)
- [popup.css](d:/GITHUB/download-images-fb-post/extension/popup.css)
- [background.js](d:/GITHUB/download-images-fb-post/extension/background.js)

## Cach hoat dong

1. Popup nhan link bai post Facebook va prefix ten file.
2. Service worker mo dung link do trong 1 background tab.
3. Extension thu gom anh bang photo viewer de lay nhieu anh hon.
4. Neu can, extension fallback sang cach quet link photo va anh inline.
5. Cac anh duoc dua vao download queue voi ten file ban da chon.

## Luu y

- Facebook thay doi HTML kha thuong xuyen, nen selector co the can cap nhat theo thoi diem.
- Extension can ban dang nhap tai khoan co quyen xem bai post do.
- Lan dau Coc Coc co the hoi quyen download; hay bam cho phep.
