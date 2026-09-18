import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from models import Course, CourseChunk

# Common words excluded from course-name lexical matching so a shared
# stopword (e.g. both titles containing "with") doesn't count as a match.
# Includes domain-generic words ("course", "lesson", ...) that show up in
# almost every query/title and so carry no real matching signal here.
_COURSE_NAME_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "to",
        "of",
        "in",
        "on",
        "at",
        "is",
        "it",
        "as",
        "an",
        "a",
        "by",
        "be",
        "are",
        "this",
        "that",
        "course",
        "courses",
        "class",
        "classes",
        "lesson",
        "lessons",
    }
)
# SequenceMatcher ratio above which two words are treated as "the same
# word" for course-name matching, tolerant of a small typo (e.g. "Antropic").
_WORD_MATCH_RATIO = 0.82
# Below this squared-L2 embedding distance, treat the catalog's nearest
# neighbor as a confident semantic match even with no shared words. Kept
# tight (empirically, unrelated queries can score below 1.3 - e.g. any
# query containing the generic word "course" skews toward a course title
# on embedding distance alone) - every real partial-title match found in
# testing also has lexical overlap, so this is a narrow safety net for
# genuine near-exact/paraphrase matches, not the primary signal.
_COURSE_DISTANCE_THRESHOLD = 1.0


def _significant_words(text: str) -> set:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _COURSE_NAME_STOPWORDS
    }


def _shares_meaningful_word(query: str, title: str) -> bool:
    """Whether query and title share a word (allowing a small typo)."""
    query_words = _significant_words(query)
    title_words = _significant_words(title)
    return any(
        qw == tw or SequenceMatcher(None, qw, tw).ratio() >= _WORD_MATCH_RATIO
        for qw in query_words
        for tw in title_words
    )


@dataclass
class SearchResults:
    """Container for search results with metadata"""

    documents: List[str]
    metadata: List[Dict[str, Any]]
    distances: List[float]
    error: Optional[str] = None

    @classmethod
    def from_chroma(cls, chroma_results: Dict) -> "SearchResults":
        """Create SearchResults from ChromaDB query results"""
        return cls(
            documents=(
                chroma_results["documents"][0] if chroma_results["documents"] else []
            ),
            metadata=(
                chroma_results["metadatas"][0] if chroma_results["metadatas"] else []
            ),
            distances=(
                chroma_results["distances"][0] if chroma_results["distances"] else []
            ),
        )

    @classmethod
    def empty(cls, error_msg: str) -> "SearchResults":
        """Create empty results with error message"""
        return cls(documents=[], metadata=[], distances=[], error=error_msg)

    def is_empty(self) -> bool:
        """Check if results are empty"""
        return len(self.documents) == 0


class VectorStore:
    """Vector storage using ChromaDB for course content and metadata"""

    def __init__(self, chroma_path: str, embedding_model: str, max_results: int = 5):
        self.max_results = max_results
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(
            path=chroma_path, settings=Settings(anonymized_telemetry=False)
        )

        # Set up sentence transformer embedding function
        self.embedding_function = (
            chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )
        )

        # Create collections for different types of data
        self.course_catalog = self._create_collection(
            "course_catalog"
        )  # Course titles/instructors
        self.course_content = self._create_collection(
            "course_content"
        )  # Actual course material

    def _create_collection(self, name: str):
        """Create or get a ChromaDB collection"""
        return self.client.get_or_create_collection(
            name=name, embedding_function=self.embedding_function
        )

    def search(
        self,
        query: str,
        course_name: Optional[str] = None,
        lesson_number: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> SearchResults:
        """
        Main search interface that handles course resolution and content search.

        Args:
            query: What to search for in course content
            course_name: Optional course name/title to filter by
            lesson_number: Optional lesson number to filter by
            limit: Maximum results to return

        Returns:
            SearchResults object with documents and metadata
        """
        # Step 1: Resolve course name if provided
        course_title = None
        if course_name:
            course_title = self._resolve_course_name(course_name)
            if not course_title:
                return SearchResults.empty(f"No course found matching '{course_name}'")

        # Step 2: Build filter for content search
        filter_dict = self._build_filter(course_title, lesson_number)

        # Step 3: Search course content
        # Use provided limit or fall back to configured max_results
        search_limit = limit if limit is not None else self.max_results

        try:
            results = self.course_content.query(
                query_texts=[query], n_results=search_limit, where=filter_dict
            )
            return SearchResults.from_chroma(results)
        except Exception as e:
            return SearchResults.empty(f"Search error: {str(e)}")

    def _resolve_course_name(self, course_name: str) -> Optional[str]:
        """Use vector search to find best matching course by name.

        Chroma's n_results=1 query always returns *some* nearest neighbor
        once the catalog is non-empty, so raw semantic distance alone can't
        tell "close enough" apart from "nothing like this exists" - e.g. an
        unrelated query can land at a smaller distance than a genuine
        partial-title match. Only accept the top match if it's either a
        confident semantic match (small distance) or shares a real word
        with the matched title (allowing a small typo).
        """
        try:
            results = self.course_catalog.query(query_texts=[course_name], n_results=1)

            if results["documents"][0] and results["metadatas"][0]:
                title = results["metadatas"][0][0]["title"]
                distance = results["distances"][0][0]
                if distance <= _COURSE_DISTANCE_THRESHOLD or _shares_meaningful_word(
                    course_name, title
                ):
                    return title
        except Exception as e:
            print(f"Error resolving course name: {e}")

        return None

    def _build_filter(
        self, course_title: Optional[str], lesson_number: Optional[int]
    ) -> Optional[Dict]:
        """Build ChromaDB filter from search parameters"""
        if not course_title and lesson_number is None:
            return None

        # Handle different filter combinations
        if course_title and lesson_number is not None:
            return {
                "$and": [
                    {"course_title": course_title},
                    {"lesson_number": lesson_number},
                ]
            }

        if course_title:
            return {"course_title": course_title}

        return {"lesson_number": lesson_number}

    def add_course_metadata(self, course: Course):
        """Add course information to the catalog for semantic search"""
        import json

        course_text = course.title

        # Build lessons metadata and serialize as JSON string
        lessons_metadata = []
        for lesson in course.lessons:
            lessons_metadata.append(
                {
                    "lesson_number": lesson.lesson_number,
                    "lesson_title": lesson.title,
                    "lesson_link": lesson.lesson_link,
                }
            )

        self.course_catalog.add(
            documents=[course_text],
            metadatas=[
                {
                    "title": course.title,
                    "instructor": course.instructor,
                    "course_link": course.course_link,
                    "lessons_json": json.dumps(
                        lessons_metadata
                    ),  # Serialize as JSON string
                    "lesson_count": len(course.lessons),
                }
            ],
            ids=[course.title],
        )

    def add_course_content(self, chunks: List[CourseChunk]):
        """Add course content chunks to the vector store"""
        if not chunks:
            return

        documents = [chunk.content for chunk in chunks]
        metadatas = [
            {
                "course_title": chunk.course_title,
                "lesson_number": chunk.lesson_number,
                "chunk_index": chunk.chunk_index,
            }
            for chunk in chunks
        ]
        # Use title with chunk index for unique IDs
        ids = [
            f"{chunk.course_title.replace(' ', '_')}_{chunk.chunk_index}"
            for chunk in chunks
        ]

        self.course_content.add(documents=documents, metadatas=metadatas, ids=ids)

    def clear_all_data(self):
        """Clear all data from both collections"""
        try:
            self.client.delete_collection("course_catalog")
            self.client.delete_collection("course_content")
            # Recreate collections
            self.course_catalog = self._create_collection("course_catalog")
            self.course_content = self._create_collection("course_content")
        except Exception as e:
            print(f"Error clearing data: {e}")

    def get_existing_course_titles(self) -> List[str]:
        """Get all existing course titles from the vector store"""
        try:
            # Get all documents from the catalog
            results = self.course_catalog.get()
            if results and "ids" in results:
                return results["ids"]
            return []
        except Exception as e:
            print(f"Error getting existing course titles: {e}")
            return []

    def get_course_count(self) -> int:
        """Get the total number of courses in the vector store"""
        try:
            results = self.course_catalog.get()
            if results and "ids" in results:
                return len(results["ids"])
            return 0
        except Exception as e:
            print(f"Error getting course count: {e}")
            return 0

    def get_all_courses_metadata(self) -> List[Dict[str, Any]]:
        """Get metadata for all courses in the vector store"""
        import json

        try:
            results = self.course_catalog.get()
            if results and "metadatas" in results:
                # Parse lessons JSON for each course
                parsed_metadata = []
                for metadata in results["metadatas"]:
                    course_meta = metadata.copy()
                    if "lessons_json" in course_meta:
                        course_meta["lessons"] = json.loads(course_meta["lessons_json"])
                        del course_meta[
                            "lessons_json"
                        ]  # Remove the JSON string version
                    parsed_metadata.append(course_meta)
                return parsed_metadata
            return []
        except Exception as e:
            print(f"Error getting courses metadata: {e}")
            return []

    def get_course_link(self, course_title: str) -> Optional[str]:
        """Get course link for a given course title"""
        try:
            # Get course by ID (title is the ID)
            results = self.course_catalog.get(ids=[course_title])
            if results and "metadatas" in results and results["metadatas"]:
                metadata = results["metadatas"][0]
                return metadata.get("course_link")
            return None
        except Exception as e:
            print(f"Error getting course link: {e}")
            return None

    def get_lesson_link(self, course_title: str, lesson_number: int) -> Optional[str]:
        """Get lesson link for a given course title and lesson number"""
        import json

        try:
            # Get course by ID (title is the ID)
            results = self.course_catalog.get(ids=[course_title])
            if results and "metadatas" in results and results["metadatas"]:
                metadata = results["metadatas"][0]
                lessons_json = metadata.get("lessons_json")
                if lessons_json:
                    lessons = json.loads(lessons_json)
                    # Find the lesson with matching number
                    for lesson in lessons:
                        if lesson.get("lesson_number") == lesson_number:
                            return lesson.get("lesson_link")
            return None
        except Exception as e:
            print(f"Error getting lesson link: {e}")

    def get_course_outline(self, course_name: str) -> Optional[Dict[str, Any]]:
        """Resolve a fuzzy course name and return its outline:
        title, course_link, and ordered lesson list (lesson_number, lesson_title, lesson_link).
        Returns None if no matching course is found."""
        import json

        try:
            resolved_title = self._resolve_course_name(course_name)
            if not resolved_title:
                return None
            results = self.course_catalog.get(ids=[resolved_title])
            if not results or "metadatas" not in results or not results["metadatas"]:
                return None
            metadata = results["metadatas"][0]
            lessons_json = metadata.get("lessons_json")
            lessons = json.loads(lessons_json) if lessons_json else []
            lessons.sort(key=lambda lesson: lesson.get("lesson_number", 0))
            return {
                "title": metadata.get("title", resolved_title),
                "course_link": metadata.get("course_link"),
                "lessons": lessons,
            }
        except Exception as e:
            print(f"Error getting course outline: {e}")
            return None
