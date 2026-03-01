from pydantic import BaseModel, ConfigDict, Field


class Actor(BaseModel):
    """GitHub Actor (User or Bot)."""

    login: str


class ReviewNode(BaseModel):
    """Single PR Review State."""

    author: Actor | None
    state: str


class ReviewConnection(BaseModel):
    """Wrapper for list of PR review nodes from GraphQL API."""

    nodes: list[ReviewNode]


class IssueNode(BaseModel):
    """Linked Issue Reference."""

    title: str
    url: str


class IssueConnection(BaseModel):
    """Wrapper for list of linked issue nodes from GraphQL API."""

    nodes: list[IssueNode]


class CommitMessage(BaseModel):
    """Container for a single commit message."""

    message: str


class CommitNode(BaseModel):
    """Single Commit in PR."""

    commit: CommitMessage


class CommitConnection(BaseModel):
    """Wrapper for list of commit nodes from GraphQL API."""

    nodes: list[CommitNode]


class FileNode(BaseModel):
    """Single file path node in GraphQL response."""

    path: str


class FileEdge(BaseModel):
    """GraphQL edge wrapper for file node."""

    node: FileNode


class FileConnection(BaseModel):
    """Wrapper for list of file edges from GraphQL API."""

    edges: list[FileEdge]


class CommentConnection(BaseModel):
    """Wrapper for PR comment count from GraphQL API."""

    model_config = ConfigDict(populate_by_name=True)
    total_count: int = Field(alias="totalCount")


class ThreadCommentNode(BaseModel):
    """Single review thread comment from GraphQL API."""

    author: Actor | None
    body: str
    createdAt: str


class ThreadCommentConnection(BaseModel):
    """Wrapper for list of review thread comments from GraphQL API."""

    nodes: list[ThreadCommentNode]


class ReviewThreadNode(BaseModel):
    """Single review thread with resolution status and comments."""

    isResolved: bool
    isOutdated: bool
    comments: ThreadCommentConnection


class ReviewThreadConnection(BaseModel):
    """Wrapper for list of review thread nodes from GraphQL API."""

    nodes: list[ReviewThreadNode]


class PullRequest(BaseModel):
    """
    GitHub Pull Request Data Representation.
    Maps GraphQL response fields to domain logic requirements.
    """

    number: int
    title: str
    body: str
    changed_files: int = Field(alias="changedFiles")
    additions: int
    deletions: int
    merged_at: str | None = Field(None, alias="mergedAt")
    author: Actor | None
    comments: CommentConnection = Field(default_factory=lambda: CommentConnection(totalCount=0))
    closing_issues_references: IssueConnection = Field(alias="closingIssuesReferences")
    reviews: ReviewConnection = Field(alias="reviews")
    commits: CommitConnection = Field(alias="commits")
    files: FileConnection = Field(default_factory=lambda: FileConnection(edges=[]))
    review_threads: ReviewThreadConnection | None = Field(None, alias="reviewThreads")


class Repository(BaseModel):
    """Root Repository Node from GraphQL."""

    pull_request: PullRequest | None = Field(alias="pullRequest")
    pull_requests: dict | None = Field(alias="pullRequests")


class GraphQLResponseData(BaseModel):
    """GraphQL response data container with repository field."""

    repository: Repository | None


class GraphQLResponse(BaseModel):
    """Standard GraphQL Response Wrapper."""

    data: GraphQLResponseData
    errors: list[dict] | None = None
