import React from 'react';
import { StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useTheme } from '../theme/ThemeContext';
import { useLanguage } from '../context/LanguageContext';
import { EmptyState } from '../components/EmptyState';

export default function AIScreen() {
  const { colors } = useTheme();
  const { t } = useLanguage();

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: colors.backgroundDark }]}>
      <EmptyState
        title={t('nav_ai')}
        description="Phase 6: Multilingual Bhashini Voice Assistant (Listening, Processing, Speaking states)"
        iconName="mic-outline"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'center', alignItems: 'center' },
});
