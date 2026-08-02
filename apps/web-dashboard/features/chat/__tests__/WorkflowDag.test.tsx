import "@testing-library/jest-dom"
import { render, screen } from "@testing-library/react"
import { WorkflowDag } from "../components/WorkflowDag"
import React from "react"

describe("WorkflowDag Component", () => {
  const sampleWorkflow = ["Extraction", "SchemaLinking", "Audit"]

  it("renders correctly in IDLE state", () => {
    render(
      <WorkflowDag
        workflowDag={sampleWorkflow}
        currentTaskIndex={0}
        workflowStatus="IDLE"
      />
    )

    expect(screen.getByText("Extraction")).toBeInTheDocument()
    expect(screen.getByText("SchemaLinking")).toBeInTheDocument()
    expect(screen.getByText("Audit")).toBeInTheDocument()
  })

  it("renders correctly in RUNNING state for the second task", () => {
    render(
      <WorkflowDag
        workflowDag={sampleWorkflow}
        currentTaskIndex={1}
        workflowStatus="RUNNING"
      />
    )

    const firstTask = screen.getByText("Extraction")
    const secondTask = screen.getByText("SchemaLinking")

    expect(firstTask).toHaveClass("text-green-700")
    expect(secondTask).toHaveClass("text-brand")
  })

  it("renders correctly in WAITING_ON_HUMAN state", () => {
    render(
      <WorkflowDag
        workflowDag={sampleWorkflow}
        currentTaskIndex={2}
        workflowStatus="WAITING_ON_HUMAN"
      />
    )

    const thirdTask = screen.getByText("Audit")

    expect(thirdTask).toHaveClass("text-orange-700")
    expect(thirdTask).toHaveClass("animate-pulse")
  })

  it("renders correctly when COMPLETED", () => {
    render(
      <WorkflowDag
        workflowDag={sampleWorkflow}
        currentTaskIndex={2}
        workflowStatus="COMPLETED"
      />
    )

    const tasks = [
      screen.getByText("Extraction"),
      screen.getByText("SchemaLinking"),
      screen.getByText("Audit")
    ]

    tasks.forEach((task) => {
      expect(task).toHaveClass("text-green-700")
    })
  })
})
