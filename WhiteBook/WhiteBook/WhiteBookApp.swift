//
//  WhiteBookApp.swift
//  WhiteBook
//
//  Created by Roshan Lodha on 4/27/26.
//

import SwiftUI
import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String, completionHandler: @escaping () -> Void) {
        ModelDownloadCoordinator.shared.handleEventsForBackgroundURLSession(identifier: identifier, completionHandler: completionHandler)
    }
}

@main
struct WhiteBookApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
