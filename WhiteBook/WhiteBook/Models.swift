//
//  Models.swift
//  WhiteBook
//

import Foundation

struct Chunk: Identifiable, Equatable {
    let id: String
    let heading_context: String
    let text_content: String
    let page_start: Int
    let page_end: Int
    let image_filename: String?
    let embedding: Data
}