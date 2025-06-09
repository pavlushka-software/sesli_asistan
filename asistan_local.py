import speech_recognition as sr
from gtts import gTTS
import pygame
import os
import json
import pyautogui # Klavye ve mouse otomasyonu için
import subprocess
import atexit
import time
import hashlib
import requests # gTTS tarafından dolaylı olarak kullanılabilir
import re # Metin işlemleri için (örn: sayı ayıklama)

# ========== KONFİGÜRASYON (AYARLAR) ========== #
AYARLAR = {
    "aktivasyon_kelimesi": "jarvis",
    "ses_hizi": False,
    "enerji_esigi": 100,
    "dinleme_baslangic_bekleme_suresi": 5.0,
    "konusma_sonu_sessizlik_suresi": 1.2,
}

# ========== SES YÖNETİMİ (Konuşma ve Ses Çalma) ========== #
class SesYonetimi:
    def __init__(self):
        try:
            pygame.mixer.init()
            self.pygame_available = True
        except pygame.error as e:
            print(f"UYARI: Pygame mixer başlatılamadı: {e}. Ses özellikleri (konuşma) çalışmayabilir.")
            self.pygame_available = False
        self.temp_files = set()
        self.cleanup_interval = 120 

    def konus(self, metin):
        if not self.pygame_available:
            print(f"🤖 (Ses Kapalı): {metin}")
            return
        try:
            print(f"🤖 Asistan: {metin}")
            file_hash = hashlib.md5(metin.encode('utf-8')).hexdigest()[:10]
            dosya_adi = f"temp_audio_{file_hash}.mp3"
            
            tts = gTTS(metin, lang='tr', slow=AYARLAR["ses_hizi"])
            tts.save(dosya_adi)
            self.temp_files.add(dosya_adi)
            self._play_sound(dosya_adi)
        except Exception as e:
            print(f"🔇 Ses üretim veya çalma hatası: {str(e)}")

    def _play_sound(self, dosya_adi):
        if not self.pygame_available:
            return
        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            pygame.mixer.music.load(dosya_adi)
            pygame.mixer.music.play()
            start_time = time.time()
            while pygame.mixer.music.get_busy():
                if time.time() - start_time > 20:
                    print("🔇 Ses oynatma zaman aşımına uğradı.")
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                    break
                pygame.time.Clock().tick(10)
        except Exception as e:
            print(f"🔇 Ses oynatma hatası ({dosya_adi}): {str(e)}")

    def _periodic_cleanup(self):
        if not self.pygame_available:
            return
        now = time.time()
        for dosya in list(self.temp_files):
            try:
                if os.path.exists(dosya) and not pygame.mixer.music.get_busy():
                    if now - os.path.getmtime(dosya) > self.cleanup_interval:
                        os.remove(dosya)
                        self.temp_files.remove(dosya)
            except Exception:
                pass

    def temizle_tum_gecici_dosyalar(self):
        if not self.pygame_available:
            return
        print("🧹 Program sonu: Geçici ses dosyaları temizleniyor...")
        if pygame.mixer.get_init():
             pygame.mixer.music.stop()
             pygame.mixer.music.unload()
        for dosya in list(self.temp_files):
            try:
                if os.path.exists(dosya): os.remove(dosya)
            except Exception as e:
                print(f"⚠️ Geçici dosya silinemedi {dosya}: {e}")
        self.temp_files.clear()
        if pygame.mixer.get_init(): pygame.mixer.quit()

# ========== DİNLEME MODÜLÜ (Sesi Yazıya Çevirme) ========== #
class Dinleyici:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = AYARLAR["enerji_esigi"]
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = AYARLAR["konusma_sonu_sessizlik_suresi"]
        try:
            self.microphone = sr.Microphone()
            print("🎤 Mikrofon hazır.")
        except Exception as e:
            print(f"🎙️ MİKROFON BAŞLATILAMADI: {e}")
            print("ℹ️ Olası Çözümler:")
            print("  - Mikrofonun bilgisayara bağlı ve çalışır durumda olduğundan emin olun.")
            print("  - `pyaudio` kütüphanesinin doğru kurulduğundan emin olun (`pip install pyaudio`).")
            self.microphone = None

    def dinle(self):
        if not self.microphone:
            print("🔇 Mikrofon bulunamadığı için dinleme yapılamıyor.")
            return ""
        try:
            with self.microphone as source:
                print(f"🔊 Dinliyorum (siz {AYARLAR['konusma_sonu_sessizlik_suresi']} saniye susana kadar)...")
                audio = self.recognizer.listen(
                    source,
                    timeout=AYARLAR["dinleme_baslangic_bekleme_suresi"],
                    phrase_time_limit=None
                )
                print("👂 Ses algılandı, yazıya çevriliyor...")
                text = self.recognizer.recognize_google(audio, language="tr-TR").lower()
                print(f"💬 Algılanan: {text}")
                return text
        except sr.WaitTimeoutError:
            return ""
        except sr.UnknownValueError:
            print("🔇 Kusura bakmayın, ne dediğinizi anlayamadım.")
            return ""
        except Exception as e:
            print(f"🎙️ Dinleme sırasında bir hata oluştu: {str(e)}")
            return ""

# ========== KOMUT SİSTEMİ (commands.json dosyasını kullanır ve parametreleri işler) ========== #
class KomutSistemi:
    def __init__(self, ses_yonetimi_nesnesi):
        self.ses_yonetimi = ses_yonetimi_nesnesi
        self.komutlar = self._load_commands()
        
    def _load_commands(self):
        try:
            with open("commands.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"📜 UYARI: 'commands.json' komut dosyası bulunamadı.")
            return {}
        except json.JSONDecodeError:
            print(f"📜 UYARI: 'commands.json' dosyası bozuk, geçerli JSON formatında değil.")
            return {}
        except Exception as e:
            print(f"📜 Komut dosyası yüklenirken hata: {str(e)}")
            return {}
    
    def islem_yap(self, soylenen_metin):
        if soylenen_metin.startswith(AYARLAR["aktivasyon_kelimesi"]):
            asıl_komut_metni = soylenen_metin[len(AYARLAR["aktivasyon_kelimesi"]):].strip()
            for anahtar, config in self.komutlar.items():
                if not isinstance(config, dict): 
                    continue
                tetikleyici_ifade = config.get("trigger_phrase", anahtar)
                if asıl_komut_metni.startswith(tetikleyici_ifade):
                    sorgu = asıl_komut_metni[len(tetikleyici_ifade):].strip()
                    self._execute_command(config, sorgu)
                    return True
        return False
    
    def _execute_command(self, config, sorgu=""):
        try:
            action = config.get("action")
            yanit_formati = config.get("response", "İsteğiniz yerine getiriliyor.")
            calistirilacak_komut_formati = config.get("command")

            yanit_metni = yanit_formati.replace("{query}", sorgu) if sorgu else yanit_formati.replace(" {query}", "").strip()
            
            if action == "run":
                if calistirilacak_komut_formati:
                    gercek_komut = calistirilacak_komut_formati.replace("{query}", sorgu) if sorgu else calistirilacak_komut_formati
                    if "{query}" in calistirilacak_komut_formati and not sorgu:
                        self.ses_yonetimi.konus(f"Ne aramamı/yapmamı istediğinizi belirtmediniz. Lütfen '{config.get('trigger_phrase', 'komut')}' dedikten sonra isteğinizi söyleyin.")
                        return
                    print(f"🚀 Komut çalıştırılıyor: {gercek_komut}")
                    subprocess.Popen(gercek_komut, shell=True)
                    self.ses_yonetimi.konus(yanit_metni)
                else:
                    print(f"⚠️ 'run' eylemi için 'command' alanı eksik: {config.get('trigger_phrase', 'Bilinmeyen komut')}")
            
            elif action == "speak":
                self.ses_yonetimi.konus(yanit_metni)
            
            elif action == "press":
                 if 'key' in config:
                    pyautogui.press(config["key"])
                    self.ses_yonetimi.konus(yanit_metni)
                 else:
                    print("⚠️ 'press' eylemi için 'key' belirtilmemiş.")
                    self.ses_yonetimi.konus("Bu komut için bir tuş ayarlanmamış.")

            elif action == "hotkey": # Klavye kısayolları için eklendi
                if 'keys' in config and isinstance(config['keys'], list):
                    try:
                        pyautogui.hotkey(*config['keys']) 
                        self.ses_yonetimi.konus(yanit_metni)
                    except Exception as e_hotkey:
                        print(f"⚠️ Hotkey hatası ({config['keys']}): {str(e_hotkey)}")
                        self.ses_yonetimi.konus("Klavye kısayolunu uygularken bir sorun oluştu.")
                else:
                    print("⚠️ 'hotkey' eylemi için 'keys' listesi belirtilmemiş veya yanlış formatta.")
                    self.ses_yonetimi.konus("Bu komut için klavye kısayolu doğru ayarlanmamış.")

            elif action == "set_system_volume":
                try:
                    match = re.search(r'\d+', sorgu) 
                    if match:
                        volume_level = int(match.group(0))
                        if 0 <= volume_level <= 100:
                            ps_scalar_value = volume_level / 100.0
                            ps_command_set_scalar = f"(New-Object -ComObject CoreAudioApi.MMDeviceEnumerator).GetDefaultAudioEndpoint(0,1).AudioEndpointVolume.MasterVolumeLevelScalar = {ps_scalar_value}"
                            
                            print(f"🔊 Sistem sesi %{volume_level} olarak ayarlanıyor...")
                            process = subprocess.Popen(['powershell.exe', '-Command', ps_command_set_scalar], 
                                                       shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            stdout, stderr = process.communicate()

                            if process.returncode == 0:
                                final_response = yanit_formati.replace("{query}", str(volume_level))
                                self.ses_yonetimi.konus(final_response)
                            else:
                                decoded_stderr = stderr.decode('cp857', errors='ignore') if stderr else ""
                                print(f"⚠️ PowerShell ses ayarlama hatası: {decoded_stderr}")
                                self.ses_yonetimi.konus("Sistem sesini ayarlarken bir sorun oluştu. Lütfen PowerShell komutunun doğru çalıştığından emin olun.")
                        else:
                            self.ses_yonetimi.konus("Ses seviyesi 0 ile 100 arasında bir değer olmalıdır.")
                    else:
                        self.ses_yonetimi.konus("Lütfen ayarlanacak ses seviyesini belirtin, örneğin 'sesi 30 ayarla'.")
                except ValueError:
                    self.ses_yonetimi.konus("Ses seviyesi olarak geçerli bir sayı belirtmediniz.")
                except Exception as e_vol:
                    print(f"🔊 Ses ayarlama genel hatası: {str(e_vol)}")
                    self.ses_yonetimi.konus("Sistem sesini ayarlarken beklenmedik bir sorun oluştu. Bu özellik Windows'ta daha iyi çalışabilir.")

            if config.get("exit"):
                self.ses_yonetimi.konus(yanit_metni)
                raise SystemExit("Program kullanıcı tarafından sonlandırıldı.")
                
        except SystemExit:
            raise
        except Exception as e:
            print(f"⚙️ Komut işlenirken genel hata ('{config.get('trigger_phrase', 'Bilinmeyen')}'): {str(e)}")
            import traceback
            traceback.print_exc()
            self.ses_yonetimi.konus("Komutu işlerken bir sorunla karşılaştım.")

# ========== ANA UYGULAMA (Sadece Komut Odaklı) ========== #
class Asistan:
    def __init__(self):
        self.ses_yonetimi = SesYonetimi()
        self.dinleyici = Dinleyici()
        self.komut_sistemi = KomutSistemi(self.ses_yonetimi)
        
        atexit.register(self._program_kapanirken_temizlik_yap)
        
    def _program_kapanirken_temizlik_yap(self):
        print("🧼 Programdan çıkılıyor, son temizlikler yapılıyor...")
        self.ses_yonetimi.temizle_tum_gecici_dosyalar()
        
    def baslat(self):
        self.ses_yonetimi.konus("Asistan komutlarınızı bekliyor.")
        
        last_cleanup_time = time.time()

        while True:
            try:
                if time.time() - last_cleanup_time > self.ses_yonetimi.cleanup_interval:
                    self.ses_yonetimi._periodic_cleanup()
                    last_cleanup_time = time.time()

                söylenen_söz = self.dinleyici.dinle()
                
                if söylenen_söz:
                    print(f"👤 Kullanıcı: {söylenen_söz}")
                    
                    if söylenen_söz.startswith(AYARLAR["aktivasyon_kelimesi"]):
                        if not self.komut_sistemi.islem_yap(söylenen_söz):
                            komut_sonrasi_kisim = söylenen_söz[len(AYARLAR["aktivasyon_kelimesi"]):].strip()
                            if komut_sonrasi_kisim:
                                self.ses_yonetimi.konus("Bu komutu anlayamadım veya komut listemde bulunmuyor.")
                            else:
                                self.ses_yonetimi.konus("Evet, sizi dinliyorum?") 
            
            except SystemExit:
                print("🚪 Asistan kapatılıyor...")
                break 
            except KeyboardInterrupt:
                self.ses_yonetimi.konus("Program sonlandırılıyor.")
                break
            except Exception as e:
                print(f"🔥 ANA DÖNGÜDE KRİTİK HATA: {str(e)}")
                import traceback
                traceback.print_exc()
                self.ses_yonetimi.konus("Çok üzgünüm, beklenmedik bir sorunla karşılaştım. Lütfen konsol çıktılarını kontrol edin.")
                time.sleep(2)

if __name__ == "__main__":
    try:
        print("🚀 Komut tabanlı asistan başlatılıyor...")
        asistan_uygulamasi = Asistan()
        asistan_uygulamasi.baslat()
    except Exception as e:
        print(f"💥 Uygulama başlatılırken çok ciddi bir hata oluştu: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("👋 Asistan programı tamamen sonlandı.")