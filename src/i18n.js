import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import hi from './locales/hi.json'
import mr from './locales/mr.json'

export const supportedLanguages = ['mr', 'en', 'hi']
export const languageStorageKey = 'smartcivic.language'

function getStoredLanguage() {
  try {
    const stored = window.localStorage.getItem(languageStorageKey)
    return supportedLanguages.includes(stored) ? stored : 'en'
  } catch (error) {
    console.error('Unable to read the saved language preference.', error)
    return 'en'
  }
}

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      hi: { translation: hi },
      mr: { translation: mr },
    },
    lng: getStoredLanguage(),
    fallbackLng: 'en',
    keySeparator: false,
    interpolation: { escapeValue: false },
    returnEmptyString: false,
    react: { useSuspense: false },
  })

document.documentElement.lang = i18n.resolvedLanguage || 'en'

i18n.on('languageChanged', (language) => {
  const resolvedLanguage = supportedLanguages.includes(language) ? language : 'en'
  document.documentElement.lang = resolvedLanguage
  try {
    window.localStorage.setItem(languageStorageKey, resolvedLanguage)
  } catch (error) {
    console.error('Unable to save the language preference.', error)
  }
})

export function tr(key, options) {
  return i18n.t(key, options)
}

export default i18n