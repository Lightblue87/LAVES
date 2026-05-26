import SwiftUI
import UIKit

struct ScanHistoryPickerView<Destination: View>: View {
    @ObservedObject var service: ScanHistoryService
    let title: String
    let destination: (ScanEntry) -> Destination
    @State private var isSettingsPresented = false
    @State private var isClearAllPresented = false
    @State private var isClearImagesPresented = false

    private var removableImageCount: Int {
        service.entries.filter { !$0.isPinned && $0.thumbnailFileName != nil }.count
    }

    private var unpinnedCount: Int {
        service.entries.filter { !$0.isPinned }.count
    }

    private var pinnedCount: Int {
        service.entries.filter(\.isPinned).count
    }

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
                if let loadError = service.loadError {
                    Label(loadError, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
                if service.pinnedImagesBytesExceedStorageLimit {
                    Label {
                        Text("Gepinnte Bilder überschreiten das Speicherlimit. Nicht-gepinnte Bilder werden bevorzugt entfernt.")
                    } icon: {
                        Image(systemName: "pin.circle")
                            .foregroundStyle(.orange)
                    }
                    .font(.caption)
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
                    Label("Nur Bilder löschen", systemImage: "photo.slash")
                }
                .disabled(removableImageCount == 0)

                Button(role: .destructive) {
                    isClearAllPresented = true
                } label: {
                    Label("Alles löschen", systemImage: "trash")
                }
                .disabled(unpinnedCount == 0)
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
        .confirmationDialog("Nur Bilder löschen?", isPresented: $isClearImagesPresented, titleVisibility: .visible) {
            Button("Bilder löschen", role: .destructive) {
                service.deleteAllImages(keepOCRText: true)
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            Text("\(removableImageCount) \(removableImageCount == 1 ? "Bild wird" : "Bilder werden") entfernt. OCR-Texte bleiben vollständig erhalten. Gepinnte Einträge werden nicht berührt.")
        }
        .confirmationDialog("Scan-Verlauf löschen?", isPresented: $isClearAllPresented, titleVisibility: .visible) {
            Button("Alle nicht gepinnten Scans löschen", role: .destructive) {
                service.deleteAll()
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            if pinnedCount > 0 {
                Text("\(unpinnedCount) \(unpinnedCount == 1 ? "Eintrag wird" : "Einträge werden") dauerhaft gelöscht. \(pinnedCount) gepinnte \(pinnedCount == 1 ? "Eintrag bleibt" : "Einträge bleiben") erhalten.")
            } else {
                Text("\(unpinnedCount) \(unpinnedCount == 1 ? "Eintrag wird" : "Einträge werden") dauerhaft gelöscht. Diese Aktion kann nicht rückgängig gemacht werden.")
            }
        }
    }
}

private struct ScanEntryRow: View {
    let entry: ScanEntry
    let thumbnail: UIImage?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack(alignment: .bottomTrailing) {
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

                // Multi-image badge
                if entry.isMultiImage {
                    Text("\(entry.imageCount)")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 2)
                        .background(.teal, in: Capsule())
                        .offset(x: 4, y: 4)
                }
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    if entry.isPinned {
                        Image(systemName: "pin.fill").foregroundStyle(.yellow)
                    }
                    Text(entry.timestamp.formatted(date: .abbreviated, time: .shortened))
                        .font(.caption).foregroundStyle(.secondary)
                    if entry.isMultiImage {
                        Image(systemName: "photo.stack")
                            .font(.caption).foregroundStyle(.teal)
                    }
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
    @State private var pending: ScanHistorySettings
    @State private var impact: ScanHistoryCleanupPolicy.Result?
    @State private var isDestructiveConfirmPresented = false

    init(service: ScanHistoryService) {
        self.service = service
        _pending = State(initialValue: service.settings)
    }

    private var hasChanges: Bool { pending != service.settings }

    private var hasDestructiveImpact: Bool {
        guard let impact else { return false }
        return impact.removedEntries > 0 || impact.removedImages > 0
    }

    var body: some View {
        Form {
            Section("Speicherung") {
                Toggle("Historie aktiviert", isOn: $pending.isHistoryEnabled)
                Toggle("Bilder automatisch komprimieren", isOn: $pending.compressImages)
                Toggle("Nur Thumbnails speichern", isOn: $pending.storeThumbnailsOnly)
                Toggle("OCR-Text behalten bei Bildlöschung", isOn: $pending.keepOCRTextWhenDeletingImages)
            }

            Section("Limits") {
                Picker("Maximale Einträge", selection: $pending.maxEntries) {
                    ForEach(ScanHistoryEntryLimit.allCases) { limit in
                        Text(limit.title).tag(limit)
                    }
                }

                Picker("Maximales Alter", selection: $pending.maxAge) {
                    ForEach(ScanHistoryAgeLimit.allCases) { limit in
                        Text(limit.title).tag(limit)
                    }
                }

                Picker("Speicherlimit", selection: $pending.storageLimit) {
                    ForEach(ScanHistoryStorageLimit.allCases) { limit in
                        Text(limit.title).tag(limit)
                    }
                }
            }

            if let impact, hasDestructiveImpact {
                Section {
                    Label {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Diese Änderung würde sofort wirksam:")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if impact.removedEntries > 0 {
                                Text("• \(impact.removedEntries) \(impact.removedEntries == 1 ? "Eintrag" : "Einträge") werden gelöscht")
                                    .font(.caption)
                            }
                            if impact.removedImages > 0 {
                                Text("• \(impact.removedImages) \(impact.removedImages == 1 ? "Bild wird" : "Bilder werden") entfernt")
                                    .font(.caption)
                            }
                        }
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                    }
                }
            }

            Section {
                Button("Einstellungen übernehmen") {
                    if hasDestructiveImpact {
                        isDestructiveConfirmPresented = true
                    } else {
                        service.settings = pending
                        dismiss()
                    }
                }
                .disabled(!hasChanges)

                Button("Zurücksetzen", role: .cancel) {
                    pending = service.settings
                }
                .disabled(!hasChanges)
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
                Button("Fertig") { dismiss() }
            }
        }
        .onChange(of: pending) { _, new in
            impact = new != service.settings ? service.previewCleanup(with: new) : nil
        }
        .confirmationDialog(
            "Einstellungen anwenden?",
            isPresented: $isDestructiveConfirmPresented,
            titleVisibility: .visible
        ) {
            Button("Übernehmen und löschen", role: .destructive) {
                service.settings = pending
                dismiss()
            }
            Button("Abbrechen", role: .cancel) {}
        } message: {
            if let impact {
                let entries = impact.removedEntries > 0
                    ? "\(impact.removedEntries) \(impact.removedEntries == 1 ? "Eintrag" : "Einträge") und "
                    : ""
                let images = impact.removedImages > 0
                    ? "\(impact.removedImages) \(impact.removedImages == 1 ? "Bild" : "Bilder")"
                    : ""
                Text("Beim Übernehmen werden \(entries)\(images) unwiderruflich gelöscht. Gepinnte Einträge bleiben erhalten.")
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

    private var declarations: [AdditiveDeclaration] {
        AdditiveDeclarationParser.parse(text: entry.ocrText, additives: store.additives)
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
                if declarations.isEmpty && matches.isEmpty {
                    Text("Keine E-Nummern oder Stoffnamen erkannt.")
                        .foregroundStyle(.secondary)
                }
                // Structured declarations (with amounts) — highest quality
                ForEach(declarations) { decl in
                    HStack(spacing: 10) {
                        Image(systemName: decl.confidence.icon)
                            .foregroundStyle(declarationColor(decl.confidence))
                            .frame(width: 20)
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(decl.substanceName).font(.subheadline)
                                if let amount = decl.amount {
                                    Text("–").foregroundStyle(.secondary)
                                    Text(amount.displayString).font(.subheadline)
                                }
                            }
                            if let matched = decl.matchedAdditive, !matched.eNumber.isEmpty {
                                Text(matched.eNumber).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
                // Unstructured matches (E-number found but no amount structure)
                let declaredNames = Set(declarations.map { $0.substanceName.lowercased() })
                let unstructuredMatches = matches.filter {
                    !declaredNames.contains($0.additive.name.lowercased())
                    && !declaredNames.contains($0.matchedText.lowercased())
                }
                ForEach(unstructuredMatches) { match in
                    Button {
                        selectedMatch = match
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(match.additive.displayTitle).font(.headline).foregroundStyle(.primary)
                            Text("Erkannt: \(match.matchedText)").foregroundStyle(.secondary)
                            Text("Tierarten: \(match.additive.normalizedSpecies)")
                                .font(.caption).foregroundStyle(.secondary)
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

    private func declarationColor(_ confidence: AdditiveDeclarationConfidence) -> Color {
        switch confidence {
        case .exactMatch:    return .green
        case .exactNoAmount: return .teal
        case .fuzzyMatch:    return .orange
        case .noDBMatch:     return .secondary
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
