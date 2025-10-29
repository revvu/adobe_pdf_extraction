import argparse
import logging
import os
from pathlib import Path

import zipfile
import json

from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.exception.exceptions import ServiceApiException, ServiceUsageException, SdkException
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
from adobe.pdfservices.operation.io.stream_asset import StreamAsset
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdfjobs.jobs.extract_pdf_job import ExtractPDFJob
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_element_type import ExtractElementType
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_renditions_element_type import \
    ExtractRenditionsElementType
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_pdf_params import ExtractPDFParams
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.table_structure_type import TableStructureType
from adobe.pdfservices.operation.pdfjobs.result.extract_pdf_result import ExtractPDFResult

from dotenv import load_dotenv
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO)



# This sample illustrates how to extract Text Information from PDF.
#
# Refer to README.md for instructions on how to run the samples & understand output zip file.

class ExtractTextInfoFromPDF:
    def __init__(self, base_dir: Path):
        try:
            pdf_path = self._locate_pdf(base_dir)
            with pdf_path.open('rb') as file:
                input_stream = file.read()
            
            # Initialize PDF Services client
            credentials = ServicePrincipalCredentials(
                client_id=os.getenv('PDF_SERVICES_CLIENT_ID'),
                client_secret=os.getenv('PDF_SERVICES_CLIENT_SECRET')
            )
            pdf_services = PDFServices(credentials=credentials)
            
            # Upload PDF to Adobe services
            input_asset = pdf_services.upload(input_stream=input_stream, mime_type=PDFServicesMediaType.PDF)
            
            # Create and submit extraction job
            pdf_services_response = self._execute_extraction_job(pdf_services, input_asset)
            
            # Download extraction results
            output_file_path = self._download_results(pdf_services, pdf_services_response, base_dir)
            

        except (ServiceApiException, ServiceUsageException, SdkException) as e:
            logging.exception(f'Exception encountered while executing operation: {e}')

    def _execute_extraction_job(self, pdf_services: PDFServices, input_asset):
        """Stage 4: Create and submit extraction job, then wait for results."""
        # Create parameters for the job
        extract_pdf_params = ExtractPDFParams(
            elements_to_extract=[ExtractElementType.TEXT, ExtractElementType.TABLES],
            elements_to_extract_renditions=[ExtractRenditionsElementType.TABLES],
            add_char_info=False,
            styling_info=False,
            table_structure_type=TableStructureType.CSV,
        )

        # Create and submit job
        extract_pdf_job = ExtractPDFJob(input_asset=input_asset, extract_pdf_params=extract_pdf_params)
        location = pdf_services.submit(extract_pdf_job)
        
        # Get job result
        return pdf_services.get_job_result(location, ExtractPDFResult)

    def _download_results(self, pdf_services: PDFServices, pdf_services_response, base_dir: Path) -> Path:
        """Stage 5: Download extraction results and save to disk."""
        # Get content from the resulting asset
        result_asset: CloudAsset = pdf_services_response.get_result().get_resource()
        stream_asset: StreamAsset = pdf_services.get_content(result_asset)

        # Save results to file
        output_file_path = self.create_output_file_path(base_dir)
        with open(output_file_path, "wb") as file:
            file.write(stream_asset.get_input_stream())
        
        return output_file_path

    def _locate_pdf(self, base_dir: Path) -> Path:
        base_dir.mkdir(parents=True, exist_ok=True)
        pdf_files = sorted(base_dir.glob("*.pdf"))
        if not pdf_files:
            raise FileNotFoundError(f"No PDF files found in {base_dir}")
        if len(pdf_files) > 1:
            raise FileExistsError(f"Multiple PDF files found in {base_dir}; please keep only one.")
        return pdf_files[0]

    # Generates a string containing a directory structure and file name for the output file
    @staticmethod
    def create_output_file_path(base_dir: Path) -> Path:
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / "extract.zip"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract text and table data from a PDF using Adobe PDF Services.")
    parser.add_argument(
        "directory",
        nargs="?",
        default="CabanaClub",
        help="Directory containing the source PDF; results will be written here as well.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    ExtractTextInfoFromPDF(Path(args.directory))
