import SwiftUI
import UIKit

struct ScanHistoryPickerView<Destination: View>: View {
    @ObservedObject var service: ScanHistoryService
    let title: String
    let destination: (ScanEntry) -> Destination
    @State private var isSettingsPresented = false
    @State private var isClearAllPresented = false
    @State private var isClearImagesPresented = false

    var body: some View {
        List {
            Section("Status") {
                LabeledContent("Gespeicherte Scans", value: "\(service.stats.entryCount)")
                LabeledContent("Bilder", value: "\(service.stats.imageCount)")
                LabeledContent("Speicher", value: service.stats.formattedBytes)
                if service.stats.orphanImageCount > 0 {
                    LabeledContent("Verwaiste Bilder", value: "\(service.stats.orphanImageCount)")
                }
                if service.stats.missingImageCount > 0 {
                    LabeledContent("Fehlende Bilder", value: "\(service.stats.missingImageCount)")
                }
                if let lastCleanup = service.lastCleanup {
                    LabeledContent("Letzte Bereinigung", value: lastCleanup.lastRun.formatted(date: .abbreviated, time: .shortened))
                    Text(lastCleanup.summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    LabeledContent("Letzte Bereinigung", value: "Noch nicht ausgeführt")
                }
            }

            Section("Bereinigung") {
                Button {
                    service.cleanupNow()
                } label: {
                    Label("Historie bereinigen", systemImage: "wand.and.stars")
                }

                Button {
                    isClearImagesPresented = true
                } label: {
                    Label("Nur Bilder löschen", systemImage: "photo.badge.minus")
                }

                Button(role: .destructive) {
                    isClearAllPresented = true
                } label: {
                    Label("Alles löschen", systemImage: "trash")
                }

                Toggle("OCR-Texte bei Bildlöschung behalten", isOn: $service.settings.keepOCRTextWhenDeletingImages)
            }

            if service.entries.isEmpty {
                ContentUnavailableView(
                    "Keine Scans",
                    systemImage: "clock.arrow.circlepath",
                    description: Text("Scans werden nach dem Erfassen im Scan-Reiter hier angezeigt.")
                )
            } else {
                Section("Einträge") {
                    ForEach(service.entries) { entry in
                        NavigationLink {
                            destination(entry)
                        } label: {
                            ScanEntryRow(entry: entry, thumbnail: service.thumbnail(for: entry))
                        }
                        .swipeActions(edge: .leading, allowsFullSwipe: true) {
                            Button {
                                service.togglePinned(entry)
                            } label: {
                                Label(entry.isPinned ? "Lösen" : "Pinnen", systemImage: entry.isPinned ? "pin.slash" : "pin")
                            }
                            .tint(.yellow)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                service.delete(entry)
                            } label: {
                                Label("Löschen", systemImage: "trash")
                            }
                        }
                        .contextMenu {
                            Button {
                                service.togglePinned(entry)
                            } label: {
                                Label(entry.isPinned ? "Nicht mehr pinnen" : "Wichtigen Scan pinnen", systemImage: entry.isPinned ? "pin.slash" : "pin")
                            }

                            Button(role: .destructive) {
                                service.delete(entry)
                            } label: {
                                Label("Eintrag löschen", systemImage: "trash")
                            }
                        }
                    }
                    .onDelete { service.delete(at: $0) }
                }
            }
        }
        .navigationTitle(title)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    isSettingsPresented = true
                } label: {
                    Image(systemName: "gearshape")
                }
                .accessibilityLabel("Historie-Einstellungen")
            }
        }
        .sheet(isPresented: $isSettingsPresented) {
            NavigationStack {
                ScanHistorySettingsView(service: service)
            }
        }
        .confirmationDialog("Nur gespeicherte Bilder löschen?", isPresented: $isClearImagesPresented, titleVisibility: .visible) {
            Button("Bilder löschen") {
                service.deleteAllImages(keepOCRText: service.settings.keepOCRTextWhenDeletingImages)
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("OCR-Texte bleiben erhalten, wenn die Option aktiviert ist. Gepinnte Einträge bleiben geschützt.")
        }
        .confirmationDialog("Historie löschen?", isPresented: $isClearAllPresented, titleVisibility: .visible) {
            Button("Alle nicht gepinnten Scans löschen", role: .destructive) {
                service.deleteAll()
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("Gepinnte Scans werden nicht automatisch gelöscht.")
        }
    }
}

private struct ScanEntryRow: View {
    let entry: ScanEntry
    let thumbnail: UIImage?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Group {
                if let img = thumbnail {
                    Image(uiImage: img)
                        .resizable()
                        .scaledToFill()
                } else {
                    Color.secondary.opacity(0.15)
                        .overlay {
                            Image(systemName: "photo")
                                .foregroundStyle(.secondary)
                        }
                }
            }
            .frame(width: 58, height: 58)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    if entry.isPinned {
                        Image(systemName: "pin.fill")
                            .foregroundStyle(.yellow)
                    }
                    Text(entry.timestamp.formatted(date: .abbreviated, time: .shortened))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text(entry.ocrSnippet.isEmpty ? "Kein OCR-Text" : entry.ocrSnippet)
                    .font(.subheadline)
                    .lineLimit(3)
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ScanHistorySettingsView: View {
    @ObservedObject var service: ScanHistoryService
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section("Speicherung") {
                Toggle("Historie aktiviert", isOn: $service.settings.isHistoryEnabled)
                Toggle("Bilder automatisch komprimieren", isOn: $service.settings.compressImages)
                Toggle("Nur Thumbnails speichern", isOn: $service.settings.storeThumbnailsOnly)
                Toggle("OCR-Text behalten bei Bildlöschung", isOn: $service.settings.keepOCRTextWhenDeletingImages)
            }

            Section("Limits") {
                Picker("Maximale Einträge", selection: $service.settings.maxEntries) {
                    ForEach(ScanHistoryEntryLimit.allCases) { limit in
                        Text(limit.title).tag(limit)
                    }
                }

                Picker("Maximales Alter", selection: $service.settings.maxAge) {
                    ForEach(ScanHistoryAgeLimit.allCases) { limit in
                        Text(limit.title).tag(limit)
                    }
                }

                Picker("Speicherlimit", selection: $service.settings.storageLimit) {
                    ForEach(ScanHistoryStorageLimit.allCases) { limit in
                        Text(limit.title).tag(limit)
                    }
                }
            }

            Section("Datenschutz") {
                Text("Alle Scans bleiben lokal auf diesem Gerät. Es findet keine Cloud-Synchronisation, Telemetrie oder automatischer Upload statt.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Historie")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("Fertig") {
                    dismiss()
                }
            }
        }
    }
}

struct AdditiveScanResultView: View {
    let entry: ScanEntry
    @ObservedObject var store: AdditiveStore
    @ObservedObject var scanHistory: ScanHistoryService

    @State private var selectedMatch: AdditiveMatch?
    private let scanService = IngredientScanService()

    private var detectedAnimals: [DetectedAnimal] {
        scanService.detectedAnimals(in: entry.ocrText)
    }

    private var matches: [AdditiveMatch] {
        scanService.matchAdditives(in: entry.ocrText, additives: store.additives)
    }

    var body: some View {
        List {
            Section("Bild") {
                if let image = scanHistory.thumbnail(for: entry) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                LabeledContent("Scan", value: entry.timestamp.formatted(date: .abbreviated, time: .shortened))
            }

            Section("Erkannte Tierart") {
                if detectedAnimals.isEmpty {
                    Text("Keine Tierart erkannt")
                        .foregroundStyle(.secondary)
                } else {
                    Text(detectedAnimals.map(\.label).joined(separator: ", "))
                }
            }

            Section("Gefundene Zusatzstoffe") {
                if matches.isEmpty {
                    Text("Keine E-Nummern oder Stoffnamen erkannt.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(matches) { match in
                        Button {
                            selectedMatch = match
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(match.additive.displayTitle)
                                    .font(.headline)
                                    .foregroundStyle(.primary)
                                Text("Erkannt: \(match.matchedText)")
                                    .foregroundStyle(.secondary)
                                Text("Tierarten: \(match.additive.normalizedSpecies)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            Section("Gelesener Text") {
                Text(entry.ocrText)
                    .font(.footnote)
                    .textSelection(.enabled)
            }
        }
        .navigationTitle("Scan-Auswertung")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selectedMatch) { match in
            AdditiveDetailSheet(additive: match.additive)
        }
    }
}

private struct AdditiveDetailSheet: View {
    let additive: Additive
    @Environment(\.dismiss) private var dismiss
    @State private var valueText = ""
    @State private var result: EvaluationResult?

    var body: some View {
        NavigationStack {
            Form {
                Section("Zusatzstoff") {
                    LabeledContent("Kennnummer", value: additive.eNumber)
                    LabeledContent("Name", value: additive.name)
                    LabeledContent("Tierarten", value: additive.normalizedSpecies)
                    if let regulation = additive.regulation, !regulation.isEmpty {
                        LabeledContent("Rechtsgrundlage", value: regulation)
                    }
                    if let sourceFile = additive.sourceFile {
                        let page = additive.sourcePage.map { ":S.\($0)" } ?? ""
                        LabeledContent("Quelle", value: "\(sourceFile)\(page)")
                    }
                }

                Section("Grenzwerte") {
                    let unit = additive.unit ?? "mg/kg"
                    if let min = additive.minMgKg {
                        LabeledContent("Mindestwert", value: "\(min.formatted(.number.precision(.fractionLength(0...3)))) \(unit)")
                    }
                    if let max = additive.maxMgKg {
                        LabeledContent("Höchstwert", value: "\(max.formatted(.number.precision(.fractionLength(0...3)))) \(unit)")
                    }
                    if additive.minMgKg == nil && additive.maxMgKg == nil {
                        Text("Keine Grenzwerte hinterlegt")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Schnellprüfung") {
                    TextField("Laborwert \(additive.unit ?? "mg/kg")", text: $valueText)
                        .keyboardType(.decimalPad)
                    Button("Prüfen") {
                        guard let v = Double(valueText.replacingOccurrences(of: ",", with: ".")) else { return }
                        result = EvaluationService.evaluate(value: v, additive: additive)
                    }
                    .disabled(Double(valueText.replacingOccurrences(of: ",", with: ".")) == nil)
                }

                if let result {
                    ResultSection(result: result)
                }
            }
            .navigationTitle(additive.displayTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") { dismiss() }
                }
            }
        }
    }
}
