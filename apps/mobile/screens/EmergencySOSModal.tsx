import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useTheme } from '../theme/ThemeContext';
import { Button } from '../components/Button';
import { RootStackScreenProps } from '../navigation/types';

export default function EmergencySOSModal({ navigation }: RootStackScreenProps<'EmergencySOSModal'>) {
  const { colors, typography } = useTheme();

  return (
    <View style={[styles.container, { backgroundColor: colors.sosBackground }]}>
      <Text style={[typography.h1, { color: colors.sosForeground, marginBottom: 8 }]}>
        EMERGENCY SOS
      </Text>
      <Text style={[typography.bodyMedium, { color: colors.sosForeground, textAlign: 'center', marginBottom: 24 }]}>
        Phase 5: Swipe-to-confirm, countdown, and 2G SMS fallback
      </Text>
      <Button
        title="Close Modal"
        onPress={() => navigation.goBack()}
        variant="secondary"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
});
