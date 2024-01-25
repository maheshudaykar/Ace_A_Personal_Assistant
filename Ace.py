import pyttsx3
import speech_recognition as sr

def speak(text):
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    Id = r'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_EN-US_DAVID_11.0'
    engine.setProperty('voice',Id)
    engine.say(text=text)
    engine.runAndWait()

speak("Hello, I am Ace. How can I help you?")

def speech_recognition():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening...")
        r.pause_threshold = 1
        audio = r.listen(source,0,8)
        
    try:
         print("Recognizing...")    
         query = r.recognize_google(audio, language='en-in')
         return query.lower()
    
    except:
        return ""
# Call the speech_recognition function and store the result
recognized_text = speech_recognition()

# Print the recognized text
print(recognized_text)
