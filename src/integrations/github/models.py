from pydantic import BaseModel, ConfigDict, Field


class Actor(BaseModel):
    """GitHub Actor (User or Bot)."""

    login: str


class ReviewNode(BaseModel):
    """Single PR Review State."""

    author: Actor | None
    state: str


class ReviewConnection(BaseModel):
    nodes: list[ReviewNode]


class IssueNode(BaseModel):
    """Linked Issue Reference."""

    title: str
    url: str


class IssueConnection(BaseModel):
    nodes: list[IssueNode]


class CommitMessage(BaseModel):
    message: str


class CommitNode(BaseModel):
    """Single Commit in PR."""

    commit: CommitMessage


class CommitConnection(BaseModel):
    nodes: list[CommitNode]


class FileNode(BaseModel):
    path: str


class FileEdge(BaseModel):
    node: FileNode


class FileConnection(BaseModel):
    edges: list[FileEdge]


class CommentConnection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    total_count: int = Field(alias="totalCount")


class ThreadCommentNode(BaseModel):
    author: Actor | None
    body: str
    createdAt: str


class ThreadCommentConnection(BaseModel):
    nodes: list[ThreadCommentNode]


class ReviewThreadNode(BaseModel):
    isResolved: bool
    isOutdated: bool
    comments: ThreadCommentConnection


class ReviewThreadConnection(BaseModel):
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
    repository: Repository | None


class GraphQLResponse(BaseModel):
    """Standard GraphQL Response Wrapper."""

    data: GraphQLResponseData
    errors: list[dict] | None = None
