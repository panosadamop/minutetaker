// UI strings in English and Greek (NFR-05).
import { createContext, useContext } from 'react';

const en = {
  record: 'Record', library: 'Library', settings: 'Settings', newMeeting: 'New meeting',
  title: 'Title', platform: 'Platform', participants: 'Participants', participantsHint: 'Comma-separated — put your own name first',
  agenda: 'Agenda (optional)', microphone: 'Microphone', systemAudio: 'System audio (other participants)',
  defaultDevice: 'Default device', start: 'Start recording', pause: 'Pause', resume: 'Resume', stop: 'Stop & process',
  importFile: 'Import a recording or transcript',
  importHint: 'Drop audio/video (mp3, m4a, wav, mp4, mov, mkv, avi, wmv…), a transcript (Teams/Zoom/Meet .vtt, .srt, .txt, .docx, .pdf) or a WhatsApp chat export (.txt, or .zip with media to include voice notes) — or click to choose',
  pasteTranscript: 'Paste a transcript or chat instead', pastePlaceholder: 'Paste a Teams / Zoom / Meet transcript, a WhatsApp chat or plain meeting notes…',
  importText: 'Import text', playVoiceNote: 'Play voice note', srcTranscript: 'Imported transcript', srcChat: 'Chat export',
  consentTitle: 'Consent required', consentBody: 'Recording people without their knowledge is illegal in Greece (Penal Code 370A) and under GDPR requires a lawful basis. Inform all participants before you start. You can paste this notice into the meeting chat:',
  copy: 'Copy', copied: 'Copied', confirmConsent: 'Participants are informed — start', cancel: 'Cancel',
  search: 'Search transcripts, minutes and summaries…', date: 'Date', duration: 'Duration', status: 'Status',
  noMeetings: 'No meetings yet. Record one or import a recording or transcript.', transcript: 'Transcript', minutes: 'Minutes',
  summary: 'Summary', export: 'Export', generate: 'Generate minutes', regenerate: 'Regenerate', template: 'Template',
  outputLanguage: 'Output language', same: 'Same as meeting', greek: 'Greek', english: 'English', save: 'Save', saved: 'Saved',
  speakers: 'Speakers', rename: 'Rename', delete: 'Delete', confirmDelete: 'Delete this meeting and its audio permanently?',
  attendees: 'Attendees', decisions: 'Decisions', actions: 'Action items', issues: 'Open issues & risks', discussion: 'Discussion',
  nextMeeting: 'Next meeting', tldr: 'TL;DR', executive: 'Executive summary', task: 'Action', owner: 'Owner', due: 'Due',
  addRow: 'Add', onePerLine: 'one per line', includeTranscript: 'Include full transcript', includeSummary: 'Include summaries',
  includeTimestamps: 'Timestamps', download: 'Save file', retranscribe: 'Re-transcribe', noTranscript: 'No transcript yet.',
  noMinutes: 'Minutes not generated yet.', topic: 'Topic', points: 'Points',
  stt: 'Speech-to-text', llm: 'Minutes & summaries (LLM)', apiKeys: 'API keys', languages: 'Languages', storage: 'Storage & privacy',
  branding: 'Document branding', templates: 'Templates', meetingLanguage: 'Meeting language', uiLanguage: 'Interface language',
  retention: 'Delete audio after (days, 0 = never)', company: 'Company name in document header', logo: 'Logo', choose: 'Choose…',
  dataGoesTo: 'Data is sent to', localOnly: 'Stays on this computer', keySet: 'set', keyMissing: 'not set',
  engineDown: 'Engine stopped. Restart the app.', recording: 'Recording', paused: 'Paused', elapsed: 'Elapsed',
  levels: 'Input levels', macNote: 'macOS: install a loopback device such as BlackHole and select it as System audio.',
  processing: 'Processing', back: 'Back',
};
type Dict = typeof en;
const el: Dict = {
  record: 'Ηχογράφηση', library: 'Αρχείο', settings: 'Ρυθμίσεις', newMeeting: 'Νέα συνάντηση',
  title: 'Τίτλος', platform: 'Πλατφόρμα', participants: 'Συμμετέχοντες', participantsHint: 'Χωρισμένα με κόμμα — πρώτα το δικό σας όνομα',
  agenda: 'Ατζέντα (προαιρετικά)', microphone: 'Μικρόφωνο', systemAudio: 'Ήχος συστήματος (λοιποί συμμετέχοντες)',
  defaultDevice: 'Προεπιλεγμένη συσκευή', start: 'Έναρξη ηχογράφησης', pause: 'Παύση', resume: 'Συνέχεια', stop: 'Τέλος & επεξεργασία',
  importFile: 'Εισαγωγή ηχογράφησης ή απομαγνητοφώνησης',
  importHint: 'Σύρετε ήχο/βίντεο (mp3, m4a, wav, mp4, mov, mkv, avi, wmv…), απομαγνητοφώνηση (Teams/Zoom/Meet .vtt, .srt, .txt, .docx, .pdf) ή εξαγωγή συνομιλίας WhatsApp (.txt, ή .zip με πολυμέσα για να συμπεριληφθούν τα φωνητικά) — ή κάντε κλικ',
  pasteTranscript: 'Ή επικολλήστε απομαγνητοφώνηση ή συνομιλία', pastePlaceholder: 'Επικολλήστε απομαγνητοφώνηση Teams / Zoom / Meet, συνομιλία WhatsApp ή απλές σημειώσεις…',
  importText: 'Εισαγωγή κειμένου', playVoiceNote: 'Αναπαραγωγή φωνητικού μηνύματος', srcTranscript: 'Εισηγμένη απομαγνητοφώνηση', srcChat: 'Εξαγωγή συνομιλίας',
  consentTitle: 'Απαιτείται συναίνεση', consentBody: 'Η ηχογράφηση προσώπων χωρίς τη γνώση τους απαγορεύεται (ΠΚ 370Α) και κατά τον ΓΚΠΔ απαιτεί νόμιμη βάση. Ενημερώστε όλους πριν ξεκινήσετε. Μπορείτε να επικολλήσετε στη συνομιλία:',
  copy: 'Αντιγραφή', copied: 'Αντιγράφηκε', confirmConsent: 'Οι συμμετέχοντες ενημερώθηκαν — έναρξη', cancel: 'Άκυρο',
  search: 'Αναζήτηση σε απομαγνητοφωνήσεις, πρακτικά, περιλήψεις…', date: 'Ημερομηνία', duration: 'Διάρκεια', status: 'Κατάσταση',
  noMeetings: 'Δεν υπάρχουν συναντήσεις. Ηχογραφήστε ή εισάγετε ηχογράφηση ή απομαγνητοφώνηση.', transcript: 'Απομαγνητοφώνηση', minutes: 'Πρακτικά',
  summary: 'Περίληψη', export: 'Εξαγωγή', generate: 'Δημιουργία πρακτικών', regenerate: 'Αναδημιουργία', template: 'Πρότυπο',
  outputLanguage: 'Γλώσσα εξόδου', same: 'Ίδια με τη συνάντηση', greek: 'Ελληνικά', english: 'Αγγλικά', save: 'Αποθήκευση', saved: 'Αποθηκεύτηκε',
  speakers: 'Ομιλητές', rename: 'Μετονομασία', delete: 'Διαγραφή', confirmDelete: 'Οριστική διαγραφή της συνάντησης και του ήχου;',
  attendees: 'Συμμετέχοντες', decisions: 'Αποφάσεις', actions: 'Ενέργειες', issues: 'Ανοιχτά θέματα & κίνδυνοι', discussion: 'Συζήτηση',
  nextMeeting: 'Επόμενη συνάντηση', tldr: 'Με μια ματιά', executive: 'Συνοπτική περίληψη', task: 'Ενέργεια', owner: 'Υπεύθυνος', due: 'Προθεσμία',
  addRow: 'Προσθήκη', onePerLine: 'ένα ανά γραμμή', includeTranscript: 'Πλήρης απομαγνητοφώνηση', includeSummary: 'Περιλήψεις',
  includeTimestamps: 'Χρονοσημάνσεις', download: 'Αποθήκευση αρχείου', retranscribe: 'Νέα απομαγνητοφώνηση', noTranscript: 'Δεν υπάρχει απομαγνητοφώνηση.',
  noMinutes: 'Δεν έχουν δημιουργηθεί πρακτικά.', topic: 'Θέμα', points: 'Σημεία',
  stt: 'Μετατροπή ομιλίας σε κείμενο', llm: 'Πρακτικά & περιλήψεις (LLM)', apiKeys: 'Κλειδιά API', languages: 'Γλώσσες', storage: 'Αποθήκευση & απόρρητο',
  branding: 'Εμφάνιση εγγράφου', templates: 'Πρότυπα', meetingLanguage: 'Γλώσσα συνάντησης', uiLanguage: 'Γλώσσα περιβάλλοντος',
  retention: 'Διαγραφή ήχου μετά από (ημέρες, 0 = ποτέ)', company: 'Επωνυμία στην κεφαλίδα', logo: 'Λογότυπο', choose: 'Επιλογή…',
  dataGoesTo: 'Τα δεδομένα αποστέλλονται σε', localOnly: 'Παραμένουν σε αυτόν τον υπολογιστή', keySet: 'ορίστηκε', keyMissing: 'δεν ορίστηκε',
  engineDown: 'Η μηχανή σταμάτησε. Επανεκκινήστε την εφαρμογή.', recording: 'Ηχογράφηση', paused: 'Σε παύση', elapsed: 'Διάρκεια',
  levels: 'Στάθμες εισόδου', macNote: 'macOS: εγκαταστήστε συσκευή loopback (π.χ. BlackHole) και επιλέξτε την ως ήχο συστήματος.',
  processing: 'Επεξεργασία', back: 'Πίσω',
};
export const DICTS = { en, el };
export type Lang = keyof typeof DICTS;
export const I18n = createContext<{ t: Dict; lang: Lang }>({ t: en, lang: 'en' });
export const useT = () => useContext(I18n).t;
export const PLATFORMS = ['MS Teams', 'Google Meet', 'Zoom', 'Viber', 'WhatsApp', 'In-person', 'Other'];
